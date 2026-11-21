#!/usr/bin/env python3
"""Stop the robonet container safely.

When the arm driver stops, the motors keep holding their last position, and
the arm drops the next time a driver starts. So this script

  1. moves the arm to its sleep pose (go_sleep inside the container); it gives
     up after 3 arm driver read errors, i.e. when the motors do not respond,
  2. asks you to confirm you are holding the arm,
  3. switches the motors' torque off, so the arm goes limp in your hands
     (if the link to the motors is broken it cannot: then switch the arm's
     power off and on while holding it),
  4. stops and removes the container.

    python3 stop_container.py            # from the repo root
    python3 stop_container.py --no-sleep # skip step 1
    python3 stop_container.py --yes      # do not ask in step 2

Start it again with preflight, which also re-checks everything:

    python3 widowx_envs/widowx_envs/preflight/preflight.py --conf <your conf_*.py>
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "widowx_envs"))

from widowx_envs.preflight import session  # noqa: E402
from widowx_envs.preflight.config import PreflightConfig  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-sleep", action="store_true", help="do not move the arm to its sleep pose first")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--config", help="preflight config (.yaml/.json), if you use one")
    args = p.parse_args()

    config = PreflightConfig.load(args.config)
    service = config.compose_service

    if not session.container_running(REPO_ROOT, config):
        print(f"The {service} container is not running. Nothing to stop.")
        return 0

    if not args.no_sleep:
        if not session.go_to_sleep(REPO_ROOT, config):
            print("The arm is not in its sleep pose: hold it yourself before continuing.")

    print()
    print(session.hold_arm_warning())
    if not args.yes:
        try:
            answer = input(f"Holding the arm? Switch its motors off and stop the {service} container now? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Not stopped.")
            return 1

    if not session.release_and_stop(REPO_ROOT, config):
        print(f"Stopping failed. Try by hand: docker compose stop {service}")
        return 1
    print(f"{service} stopped. Remember to power the arm off if you are done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted; the container was not stopped.")
        sys.exit(130)
