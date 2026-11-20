#!/usr/bin/env python3
"""Watch the cameras live in your browser.

    python3 view_cameras.py                     # all cameras, opens http://localhost:8080
    python3 view_cameras.py --port 8090
    python3 view_cameras.py --topics /blue/image_raw /yellow/image_raw
    python3 view_cameras.py --lan               # also viewable from other machines on the network
    python3 view_cameras.py --no-browser        # just print the address
    python3 view_cameras.py --during-collection # allow it while data collection runs

Starts widowx_envs/widowx_envs/camera_viewer.py inside the running robonet
container (the cameras are ROS topics there) and opens the page. Ctrl+C
stops it. It does not run during data collection unless --during-collection
is given.

USB webcams start streaming only when someone watches them, so they can take
a few seconds to appear.
"""

import argparse
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "widowx_envs"))

from widowx_envs.preflight import session  # noqa: E402
from widowx_envs.preflight.config import PreflightConfig  # noqa: E402

CONTAINER_SCRIPT = "/home/robonet/widowx_envs/widowx_envs/camera_viewer.py"


def open_when_ready(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).close()
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)
    print(f"The viewer did not come up within {timeout_s:.0f}s; check the messages above.", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--topics", nargs="+", help="only these image topics (default: all)")
    p.add_argument("--lan", action="store_true", help="let other machines on the network view it too")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.add_argument("--during-collection", action="store_true",
                   help="allow it while data collection runs")
    p.add_argument("--config", help="preflight config (.yaml/.json), if your rig differs from the defaults")
    args = p.parse_args()

    config = PreflightConfig.load(args.config)
    if not session.container_running(REPO_ROOT, config):
        print(f"The {config.compose_service} container is not running. Start it first, e.g.:\n"
              "  python3 widowx_envs/widowx_envs/preflight/preflight.py --conf <your conf_*.py>")
        return 2

    viewer_args = ["--port", str(args.port)]
    if args.topics:
        viewer_args += ["--topics", *args.topics]
    if args.lan:
        viewer_args.append("--lan")
    if args.during_collection:
        viewer_args.append("--during-collection")
    inner = "python " + " ".join([CONTAINER_SCRIPT, *viewer_args])
    # With a terminal attached, Ctrl+C reaches the viewer inside the container.
    tty = [] if (sys.stdin.isatty() and sys.stdout.isatty()) else ["-T"]
    cmd = ["docker", "compose", "exec", *tty, config.compose_service, "bash", "-lic", inner]

    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print(f"Starting the camera viewer at {url} (Ctrl+C to stop)...", flush=True)
    try:
        rc = subprocess.run(cmd, cwd=REPO_ROOT, env=session.compose_env(REPO_ROOT, config)).returncode
        return 0 if rc in (0, 130) else rc
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
