"""Host-side preflight checks.

These run on the Alienware desktop with the system ``python3``, *outside* the
``robonet`` container: cabling, USB enumeration, the camera connector chart,
the VR headset, docker, and the dataset directories. Anything that needs ROS
lives in :mod:`checks_container` instead.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Dict, List, Tuple

from widowx_envs.preflight.core import CheckResult, Context, Status, check


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _ok(name, summary, **details) -> CheckResult:
    return CheckResult(name, Status.PASS, summary, details=details)


def _warn(name, summary, remedy="", **details) -> CheckResult:
    return CheckResult(name, Status.WARN, summary, remedy=remedy, details=details)


def _fail(name, summary, remedy="", **details) -> CheckResult:
    return CheckResult(name, Status.FAIL, summary, remedy=remedy, details=details)


def _skip(name, summary) -> CheckResult:
    return CheckResult(name, Status.SKIP, summary)


def parse_flat_yaml(text: str) -> Dict[str, str]:
    """Parse the ``key: 'value'`` subset of YAML that the connector chart uses.

    Deliberately not PyYAML: this must work with a bare system python3. The
    connector chart is always flat scalars (see ``generate_usb_config.sh``).
    """
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip("'\"")
    return out


def parse_v4l2_devices(text: str) -> List[Tuple[str, List[str]]]:
    """Parse ``v4l2-ctl --list-devices`` into ``[(header, [/dev/videoN, ...])]``.

    The header line looks like ``1080P Pro Stream (usb-0000:00:14.0-9.1):`` and
    is followed by tab-indented device nodes.
    """
    blocks: List[Tuple[str, List[str]]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw[0].isspace():
            if blocks:
                blocks[-1][1].append(raw.strip())
        else:
            blocks.append((raw.strip(), []))
    return blocks


# --------------------------------------------------------------------------- #
# repo / tooling
# --------------------------------------------------------------------------- #


@check("host.repo_root", scope="host")
def repo_root(ctx: Context) -> CheckResult:
    """Preflight is being run from a bridge_data_robot checkout."""
    missing = [
        p
        for p in ("docker-compose.yml", "widowx_envs", "generate_usb_config.sh")
        if not os.path.exists(os.path.join(ctx.repo_root, p))
    ]
    if missing:
        return _fail(
            "host.repo_root",
            f"{ctx.repo_root} does not look like bridge_data_robot (missing {', '.join(missing)})",
            remedy="cd ~/bridge_data_robot and re-run, or pass --repo-root.",
        )
    return _ok("host.repo_root", ctx.repo_root)


@check("host.docker_cli", scope="host")
def docker_cli(ctx: Context) -> CheckResult:
    """docker and the compose v2 plugin are installed."""
    if not ctx.have("docker"):
        return _fail(
            "host.docker_cli",
            "docker is not installed",
            remedy="Run ./host_install.sh (installs docker + nvidia-docker + compose).",
        )
    rc, out, err = ctx.run(["docker", "compose", "version"])
    if rc != 0:
        return _fail(
            "host.docker_cli",
            "`docker compose` is unavailable (compose v1 or plugin missing)",
            remedy="Install the compose plugin: ./host_install_scripts/docker_compose_install.sh",
            stderr=err.strip(),
        )
    return _ok("host.docker_cli", out.strip())


@check("host.docker_permissions", scope="host", requires=["host.docker_cli"])
def docker_permissions(ctx: Context) -> CheckResult:
    """The current user can talk to the docker daemon without sudo."""
    rc, _, err = ctx.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=30)
    if rc != 0:
        lowered = err.lower()
        if "permission denied" in lowered:
            remedy = (
                "sudo groupadd docker; sudo usermod -aG docker $USER, then reboot.\n"
                "See the Troubleshooting section of README.md."
            )
        else:
            remedy = "Is the docker daemon running? `sudo systemctl start docker`"
        return _fail("host.docker_permissions", err.strip().splitlines()[0] if err.strip() else "docker info failed", remedy=remedy)
    return _ok("host.docker_permissions", "docker daemon reachable")


@check("host.nvidia_runtime", scope="host", requires=["host.docker_permissions"])
def nvidia_runtime(ctx: Context) -> CheckResult:
    """The nvidia container runtime is registered (docker-compose.yml requires it)."""
    if not ctx.config.require_nvidia_runtime:
        return _skip("host.nvidia_runtime", "not required by config")
    rc, out, _ = ctx.run(["docker", "info", "--format", "{{json .Runtimes}}"], timeout=30)
    if rc == 0 and "nvidia" in out:
        return _ok("host.nvidia_runtime", "nvidia runtime registered")
    return _fail(
        "host.nvidia_runtime",
        "nvidia runtime not registered with docker",
        remedy="Run ./host_install_scripts/nvidia_docker_install.sh, then restart docker.\n"
        "Without it `docker compose up robonet` fails (the service sets runtime: nvidia).",
        runtimes=out.strip(),
    )


# --------------------------------------------------------------------------- #
# arm
# --------------------------------------------------------------------------- #


@check("host.arm_serial_port", scope="host")
def arm_serial_port(ctx: Context) -> CheckResult:
    """The WidowX U2D2 serial link is enumerated and accessible."""
    port = ctx.config.arm_serial_port
    if not os.path.exists(port):
        candidates = sorted(
            p for p in os.listdir("/dev") if p.startswith(("ttyUSB", "ttyACM", "ttyDXL"))
        ) if os.path.isdir("/dev") else []
        return _fail(
            "host.arm_serial_port",
            f"{port} does not exist",
            remedy="Check the mini-USB cable between the arm and the desktop, and that the\n"
            "arm's power brick is plugged in. If the cable is fine, the Interbotix udev\n"
            "rule may be missing: see host_install_scripts/widowx_install.sh.",
            other_tty_devices=candidates,
        )
    if not os.access(port, os.R_OK | os.W_OK):
        return _fail(
            "host.arm_serial_port",
            f"{port} exists but is not read/write for this user",
            remedy="sudo usermod -aG dialout $USER, then log out and back in.",
        )
    return _ok("host.arm_serial_port", f"{port} present and accessible")


# --------------------------------------------------------------------------- #
# cameras
# --------------------------------------------------------------------------- #


@check("host.v4l2_devices", scope="host")
def v4l2_devices(ctx: Context) -> CheckResult:
    """Every camera the collection config expects is enumerated by v4l2."""
    if not ctx.have("v4l2-ctl"):
        return _warn(
            "host.v4l2_devices",
            "v4l2-ctl not installed on the host; cannot enumerate cameras",
            remedy="sudo apt install v4l-utils (the container has it, the host needs it too\n"
            "because generate_usb_config.sh runs on the host).",
        )
    rc, out, err = ctx.run(["v4l2-ctl", "--list-devices"])
    # v4l2-ctl exits non-zero when some node can't be opened but still lists the
    # rest, so trust the output rather than the return code.
    blocks = parse_v4l2_devices(out)
    ctx.cache["v4l2_output"] = out
    ctx.cache["v4l2_blocks"] = blocks
    if not blocks:
        return _fail(
            "host.v4l2_devices",
            "no video devices found",
            remedy="Check that the cameras are plugged in. Unplug/replug and re-run.",
            stderr=err.strip(),
        )

    expected = [c for c in ctx.config.cameras if c.v4l2_name]
    missing = [c.name for c in expected if not any(c.v4l2_name in h for h, _ in blocks)]
    found = [h for h, _ in blocks]
    if missing:
        return _fail(
            "host.v4l2_devices",
            f"camera(s) not enumerated: {', '.join(missing)}",
            remedy="Replug the camera(s). If you moved a camera to a different USB port you\n"
            "must re-run ./generate_usb_config.sh afterwards.",
            found=found,
        )
    return _ok("host.v4l2_devices", f"{len(blocks)} video device(s) enumerated", found=found)


@check("host.usb_connector_chart", scope="host", requires=["host.repo_root"])
def usb_connector_chart(ctx: Context) -> List[CheckResult]:
    """usb_connector_chart.yml exists and every entry resolves to exactly one camera.

    This is the single most common source of silent, hard-to-debug data
    corruption on this rig: the chart's keys become ROS topic names and its
    values are matched against ``v4l2-ctl --list-devices`` by plain substring
    (``start_streamers.py:get_dev``). A wrong or empty value does not crash -
    it quietly binds a topic to the wrong camera.
    """
    name = "host.usb_connector_chart"
    path = os.path.join(ctx.repo_root, ctx.config.usb_connector_chart)
    if not os.path.exists(path):
        return [
            _fail(
                name,
                f"{ctx.config.usb_connector_chart} is missing",
                remedy="Run ./generate_usb_config.sh from the repo root.",
            )
        ]

    with open(path) as f:
        chart = parse_flat_yaml(f.read())
    ctx.cache["usb_chart"] = chart
    if not chart:
        return [_fail(name, f"{path} is empty", remedy="Re-run ./generate_usb_config.sh.")]

    results: List[CheckResult] = []
    blocks = ctx.cache.get("v4l2_blocks")

    # 1. Empty values are actively dangerous, not merely useless.
    empty = [k for k, v in chart.items() if not v]
    if empty:
        results.append(
            _fail(
                f"{name}.empty_entries",
                f"entries with no USB path: {', '.join(empty)}",
                remedy="generate_usb_config.sh writes an empty value for every camera that was\n"
                "not plugged in when it ran. start_streamers.py matches chart values\n"
                "against `v4l2-ctl --list-devices` with a substring test, so an empty\n"
                "value matches the FIRST device and silently binds that topic to the\n"
                "wrong camera. Delete the unused lines or replug the camera and re-run\n"
                "./generate_usb_config.sh.",
                entries=empty,
            )
        )

    # 2. Two topics pointing at one camera is always a mistake.
    seen: Dict[str, List[str]] = {}
    for key, value in chart.items():
        if value:
            seen.setdefault(value, []).append(key)
    dupes = {v: ks for v, ks in seen.items() if len(ks) > 1}
    if dupes:
        results.append(
            _fail(
                f"{name}.duplicate_entries",
                "; ".join(f"{', '.join(ks)} all point at {v}" for v, ks in dupes.items()),
                remedy="Each camera must have its own USB path. Re-run ./generate_usb_config.sh,\n"
                "and if two cameras share a hub port, move one to a different port.",
            )
        )

    # 3. Each value must resolve to exactly one v4l2 device block.
    if blocks is None:
        results.append(
            _skip(f"{name}.resolves", "v4l2-ctl unavailable; cannot verify chart entries")
        )
    else:
        for key, value in chart.items():
            if not value:
                continue  # already reported above
            matches = [h for h, devs in blocks if value in h and devs]
            if not matches:
                results.append(
                    _fail(
                        f"{name}.{key}",
                        f"'{value}' matches no connected camera",
                        remedy=f"The camera for topic /{key} is unplugged or moved ports.\n"
                        "Replug it and re-run ./generate_usb_config.sh.",
                    )
                )
            elif len(matches) > 1:
                results.append(
                    _fail(
                        f"{name}.{key}",
                        f"'{value}' is ambiguous, it matches {len(matches)} devices",
                        remedy="start_streamers.py takes the first match, so /%s may bind to the\n"
                        "wrong camera. Make the USB path in the chart more specific." % key,
                        matches=matches,
                    )
                )
            else:
                results.append(_ok(f"{name}.{key}", f"/{key} -> {matches[0]}"))

    # 4. A RealSense driven by the nodelet must not also be in the chart.
    rs_names = {c.name for c in ctx.config.realsense_cameras}
    conflicting = [k for k in chart if k in rs_names]
    if conflicting:
        results.append(
            _warn(
                f"{name}.realsense_conflict",
                f"chart also claims RealSense camera(s): {', '.join(conflicting)}",
                remedy="widowx_rs.launch starts realsense2_camera for these, and the chart makes\n"
                "multicam_server open the same /dev/video* node as a plain UVC stream.\n"
                "Two drivers on one device is likely why you see 'No RealSense devices\n"
                "were found!'. Remove these lines from usb_connector_chart.yml.",
            )
        )

    if not results:
        results.append(_ok(name, f"{len(chart)} entries"))
    return results


# --------------------------------------------------------------------------- #
# teleop
# --------------------------------------------------------------------------- #


@check("host.vr_headset", scope="host")
def vr_headset(ctx: Context) -> CheckResult:
    """The Meta Quest is connected over USB and authorised for adb."""
    name = "host.vr_headset"
    if not ctx.config.require_vr_headset:
        return _skip(name, "teleop not required by config")
    if not ctx.have("adb"):
        return _fail(
            name,
            "adb is not installed on the host",
            remedy="sudo apt install android-tools-adb",
        )
    rc, out, err = ctx.run(["adb", "devices"], timeout=30)
    if rc != 0:
        return _fail(name, "`adb devices` failed", remedy=err.strip())

    devices = []
    for line in out.splitlines()[1:]:
        if "\t" in line:
            serial, state = line.split("\t", 1)
            devices.append((serial.strip(), state.strip()))

    if not devices:
        return _fail(
            name,
            "no adb device found - the headset is not connected",
            remedy="Plug the Quest into the desktop with the USB-C cable, put it on, and\n"
            "accept the 'Allow USB debugging' prompt inside the headset.",
        )
    unauthorized = [s for s, st in devices if st != "device"]
    if unauthorized:
        return _fail(
            name,
            f"headset present but not authorised ({devices[0][1]})",
            remedy="Put the headset on and click 'Allow USB' / 'Always allow from this\n"
            "computer' on the prompt, then re-run. If no prompt appears, unplug and\n"
            "replug the cable.",
            devices=devices,
        )
    if len(devices) > 1:
        return _warn(
            name,
            f"{len(devices)} adb devices connected",
            remedy="oculus_reader picks one arbitrarily. Disconnect the other android devices.",
            devices=devices,
        )
    return _ok(name, f"headset {devices[0][0]} authorised", devices=devices)


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


@check("host.dataset_dir", scope="host")
def dataset_dir(ctx: Context) -> List[CheckResult]:
    """The host-side dataset directory exists and the container can write to it."""
    name = "host.dataset_dir"
    results: List[CheckResult] = []
    cfg = ctx.config

    legacy = os.path.expanduser(cfg.legacy_dataset_root)
    if not os.path.isdir(legacy):
        results.append(
            _fail(
                f"{name}.mount",
                f"{legacy} does not exist (it is the host side of the $DATA mount)",
                remedy=f"mkdir -p {legacy} && sudo chown -R "
                f"{cfg.container_uid}:{cfg.container_gid} {legacy}",
            )
        )
    else:
        st = os.stat(legacy)
        if (st.st_uid, st.st_gid) != (cfg.container_uid, cfg.container_gid):
            results.append(
                _fail(
                    f"{name}.ownership",
                    f"{legacy} is owned by {st.st_uid}:{st.st_gid}, "
                    f"container writes as {cfg.container_uid}:{cfg.container_gid}",
                    remedy=f"sudo chown -R {cfg.container_uid}:{cfg.container_gid} {legacy}\n"
                    "Otherwise the collection script fails with a permission error only\n"
                    "*after* you have teleoperated a trajectory.",
                )
            )
        else:
            results.append(_ok(f"{name}.ownership", f"{legacy} owned by {st.st_uid}:{st.st_gid}"))

        free_gb = shutil.disk_usage(legacy).free / 1e9
        if free_gb < cfg.min_free_gb:
            results.append(
                _fail(
                    f"{name}.free_space",
                    f"only {free_gb:.1f} GB free, want >= {cfg.min_free_gb:.0f} GB",
                    remedy="Upload and clear old sessions before collecting.",
                )
            )
        else:
            results.append(_ok(f"{name}.free_space", f"{free_gb:.1f} GB free"))

    # The cross-robot layout from the infrastructure doc. Not wired up yet, so
    # this is advisory until the unified saver lands.
    unified = os.path.expanduser(cfg.dataset_root)
    if not os.path.isdir(unified):
        results.append(
            _warn(
                f"{name}.unified_root",
                f"{unified} does not exist",
                remedy=f"The lab-wide layout is {unified}/<task_instruction>/<timestamp>.\n"
                f"sudo mkdir -p {unified} && sudo chown -R "
                f"{cfg.container_uid}:{cfg.container_gid} {unified}",
            )
        )
    else:
        results.append(_ok(f"{name}.unified_root", f"{unified} present"))
    return results


# --------------------------------------------------------------------------- #
# container liveness (host's view of it)
# --------------------------------------------------------------------------- #


@check("host.robonet_container", scope="host", requires=["host.docker_permissions"])
def robonet_container(ctx: Context) -> CheckResult:
    """The robonet container is up, so the ROS checks have something to talk to."""
    name = "host.robonet_container"
    service = ctx.config.compose_service
    rc, out, err = ctx.run(
        ["docker", "compose", "ps", "--format", "{{.Name}} {{.State}}", service],
        timeout=60,
    )
    if rc != 0:
        return _fail(
            name,
            f"`docker compose ps {service}` failed",
            remedy=f"Run it from the repo root ({ctx.repo_root}).\n{err.strip()}",
        )
    running = [l for l in out.splitlines() if "running" in l.lower()]
    if not running:
        return _fail(
            name,
            f"the {service} container is not running",
            remedy="Start it in its own terminal and leave it running:\n"
            "  cd ~/bridge_data_robot\n"
            "  USB_CONNECTOR_CHART=$(pwd)/usb_connector_chart.yml docker compose up --build robonet",
            ps_output=out.strip(),
        )
    return _ok(name, running[0].strip())
