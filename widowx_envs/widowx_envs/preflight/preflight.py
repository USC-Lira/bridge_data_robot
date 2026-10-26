#!/usr/bin/env python3
"""Pre-collection check for the LiraLab WidowX station.

Run this from the repo root on the robot desktop *before* every data
collection session::

    python3 widowx_envs/widowx_envs/preflight/preflight.py

It verifies the host side (cabling, USB enumeration, the camera connector
chart, the VR headset, docker, the dataset directory) and then hops into the
running ``robonet`` container to verify the ROS side (arm driver, camera
topics, live frames, importability of the collection stack).

Exit codes: 0 = clear to collect (possibly with warnings), 1 = at least one
blocking failure, 2 = preflight itself could not run.

Common invocations::

    # full check, and validate the exact experiment config you are about to use
    python3 .../preflight.py --conf widowx_envs/experiments/bridge_data_v2/conf_jesse.py

    # host only (e.g. before you have started the robonet container)
    python3 .../preflight.py --scope host

    # inside the container
    python3 ~/widowx_envs/widowx_envs/preflight/preflight.py --scope container
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from typing import List, Optional

# Allow running as a plain script (`python3 preflight.py`) as well as a module
# (`python3 -m widowx_envs.preflight.preflight`). The host runs it as a script
# with the system python, where widowx_envs is not installed.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "widowx_envs.preflight"

from widowx_envs.preflight.config import PreflightConfig  # noqa: E402
from widowx_envs.preflight.core import (  # noqa: E402
    CheckResult,
    Context,
    Status,
    print_report,
    print_summary,
    registered_checks,
    run_checks,
)

# Importing these modules is what registers their checks.
from widowx_envs.preflight import checks_host  # noqa: E402,F401

# Container path of this repo's widowx_envs dir (see docker-compose.yml).
CONTAINER_WIDOWX_ENVS = "/home/robonet/widowx_envs"
JSON_BEGIN = "###PREFLIGHT_JSON_BEGIN###"
JSON_END = "###PREFLIGHT_JSON_END###"


def in_container() -> bool:
    return os.path.exists("/.dockerenv")


def find_repo_root(start: Optional[str] = None) -> str:
    """Walk up from this file looking for the bridge_data_robot root."""
    path = os.path.abspath(start or __file__)
    while path != "/":
        path = os.path.dirname(path)
        if os.path.exists(os.path.join(path, "docker-compose.yml")):
            return path
    return os.getcwd()


def to_container_path(host_path: str, repo_root: str) -> str:
    """Translate a host path under <repo>/widowx_envs to its container path."""
    abs_path = os.path.abspath(host_path)
    prefix = os.path.join(repo_root, "widowx_envs")
    if abs_path.startswith(prefix):
        return CONTAINER_WIDOWX_ENVS + abs_path[len(prefix):]
    return abs_path


# --------------------------------------------------------------------------- #


def run_container_checks_from_host(args, config: PreflightConfig, repo_root: str) -> List[CheckResult]:
    """Re-invoke this script inside the robonet container and parse its report."""
    config_b64 = base64.b64encode(json.dumps(config.to_dict()).encode()).decode()
    remote = [
        "python3",
        f"{CONTAINER_WIDOWX_ENVS}/widowx_envs/preflight/preflight.py",
        "--scope", "container",
        "--config-b64", config_b64,
        "--json", "-",
    ]
    if args.conf:
        remote += ["--conf", to_container_path(args.conf, repo_root)]
    for pattern in args.only:
        remote += ["--only", pattern]
    for pattern in args.skip:
        remote += ["--skip", pattern]

    cmd = [
        "docker", "compose", "exec", "-T", config.compose_service,
        "bash", "-lic", " ".join(_quote(a) for a in remote),
    ]
    if args.verbose:
        print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if JSON_BEGIN not in proc.stdout:
        return [
            CheckResult(
                "container.*",
                Status.FAIL,
                "could not run the container-side checks",
                remedy="Run them by hand to see the error:\n"
                f"  docker compose exec {config.compose_service} bash -lic "
                f'"python3 {CONTAINER_WIDOWX_ENVS}/widowx_envs/preflight/preflight.py --scope container"',
                details={
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                    "returncode": proc.returncode,
                },
            )
        ]
    blob = proc.stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0]
    return [CheckResult.from_dict(d) for d in json.loads(blob)["results"]]


def _quote(arg: str) -> str:
    return "'" + arg.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="preflight.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--scope",
        choices=["all", "host", "container"],
        default="all",
        help="which half of the checks to run (default: all; inside the container, 'all' means 'container')",
    )
    p.add_argument("--config", help="path to a preflight config (.yaml or .json) overriding the defaults")
    p.add_argument("--config-b64", help=argparse.SUPPRESS)  # internal: host -> container handoff
    p.add_argument("--conf", help="experiment config (e.g. .../conf_jesse.py) to validate against the live ROS graph")
    p.add_argument("--only", action="append", default=[], metavar="PREFIX", help="only run checks whose name starts with PREFIX (repeatable)")
    p.add_argument("--skip", action="append", default=[], metavar="PREFIX", help="skip checks whose name starts with PREFIX (repeatable)")
    p.add_argument("--json", metavar="PATH", help="write the machine-readable report here ('-' for stdout)")
    p.add_argument("--repo-root", help="path to the bridge_data_robot checkout (default: autodetected)")
    p.add_argument("--list", action="store_true", help="list the registered checks and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="echo the commands being run")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.config_b64:
        config = PreflightConfig.from_dict(json.loads(base64.b64decode(args.config_b64)))
    else:
        config = PreflightConfig.load(args.config)

    if args.list:
        try:
            # Only importable where ROS is; on the host we list the host checks.
            from widowx_envs.preflight import checks_container  # noqa: F401
        except ImportError:
            print("(container checks not listed: rospy unavailable here)\n", file=sys.stderr)
        for chk in registered_checks():
            print(f"{chk.scope:<10} {chk.name:<36} {chk.description}")
        return 0

    repo_root = args.repo_root or find_repo_root()
    ctx = Context(config=config, repo_root=repo_root, verbose=args.verbose)
    if args.conf:
        ctx.cache["conf_file"] = os.path.abspath(args.conf) if not in_container() else args.conf

    scope = args.scope
    if scope == "all" and in_container():
        scope = "container"

    results: List[CheckResult] = []

    if scope in ("all", "host"):
        results += run_checks(ctx, "host", only=args.only, skip=args.skip)
        if args.json != "-":
            print_report(results, f"WidowX preflight - host ({repo_root})")

    if scope == "container":
        # Registering the ROS checks imports rospy, so only do it in-container.
        from widowx_envs.preflight import checks_container  # noqa: F401

        container_results = run_checks(ctx, "container", only=args.only, skip=args.skip)
        results += container_results
        if args.json != "-":
            print_report(container_results, "WidowX preflight - container (ROS)")

    elif scope == "all":
        host_blocked = any(
            r.name.startswith("host.robonet_container") and r.status is Status.FAIL
            for r in results
        )
        if host_blocked:
            results.append(
                CheckResult(
                    "container.*",
                    Status.SKIP,
                    "robonet container is not running",
                    remedy="Start it first, then re-run preflight.",
                )
            )
            print_report(results[-1:], "WidowX preflight - container (ROS)")
        else:
            container_results = run_container_checks_from_host(args, config, repo_root)
            results += container_results
            print_report(container_results, "WidowX preflight - container (ROS)")

    overall = Status.PASS
    if args.json == "-":
        # Machine-readable mode: the host side parses this out of the container's
        # stdout, which also carries bashrc noise.
        print(JSON_BEGIN)
        print(json.dumps({"results": [r.to_dict() for r in results]}, indent=None))
        print(JSON_END)
        overall = max(
            (r.status for r in results),
            key=lambda s: [Status.SKIP, Status.PASS, Status.WARN, Status.FAIL].index(s),
            default=Status.PASS,
        )
    else:
        if args.json:
            with open(args.json, "w") as f:
                json.dump({"results": [r.to_dict() for r in results]}, f, indent=2)
            print(f"\nwrote {args.json}")
        overall = print_summary(results)

    return 1 if overall is Status.FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
