#!/usr/bin/env python3
"""Run preflight, then start a data collection session.

    python3 datacollection.py widowx_envs/experiments/bridge_data_v2/conf_jesse.py

1. Runs preflight with that conf. Preflight checks the rig, fixes what it can,
   and starts the robonet container if it is not running.
2. If preflight ends without a FAIL (warnings are fine), asks whether to start
   collecting.
3. Asks you to confirm the RAIL Oculus Teleoperation app is open in the
   headset and that the headset is facing you.
4. Starts run_data_collection.py with the same conf inside the container.

When you are done, stop collection with Ctrl+C and the container with
`python3 stop_container.py`.

Any preflight option can be passed through, e.g. --build, --no-generate,
--config my_rig.yaml, -v.
"""

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "widowx_envs"))

from widowx_envs.preflight import preflight, session  # noqa: E402
from widowx_envs.preflight.config import PreflightConfig  # noqa: E402


def ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def confirm_headset() -> bool:
    """Make sure the two things preflight cannot check are done."""
    steps = [
        "Is the RAIL Oculus Teleoperation app open in the headset?\n"
        "  (If the headset restarted, the app asks you to redraw the play area first.)",
        "Is the headset placed so that it is facing you?",
    ]
    for step in steps:
        while not ask(f"\n{step}\n"):
            try:
                again = input("Do it now, then press Enter to answer again (q to quit): ").strip().lower()
            except EOFError:
                return False
            if again.startswith("q"):
                return False
    return True


def collection_command(conf_host_path: str, config) -> list:
    conf = preflight.to_container_path(os.path.abspath(conf_host_path), REPO_ROOT)
    script = f"{preflight.CONTAINER_WIDOWX_ENVS}/widowx_envs/run_data_collection.py"
    # No -T: collection is interactive and needs a terminal.
    return ["docker", "compose", "exec", config.compose_service,
            "bash", "-lic", f"python {script} {conf}"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("conf", help="experiment config, e.g. widowx_envs/experiments/bridge_data_v2/conf_jesse.py")
    p.add_argument("--config", help="preflight config (.yaml/.json), if your rig differs from the defaults")
    p.add_argument("-y", "--yes", action="store_true",
                   help="do not ask whether to start collecting (the headset confirmation is still asked)")
    args, passthrough = p.parse_known_args()

    if not os.path.exists(args.conf):
        print(f"{args.conf} does not exist.")
        return 2
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("datacollection.py needs a terminal: collection is interactive.")
        return 2

    pf_args = ["--conf", args.conf] + (["--config", args.config] if args.config else []) + passthrough
    rc = preflight.main(pf_args)
    if rc != 0:
        print("\nPreflight found failures, so collection was not started. Fix them and run this again.")
        return rc

    if not args.yes and not ask("\nPreflight passed. Start collecting data now?"):
        print("Not started. The container keeps running; run this again when ready,\n"
              "or stop it with: python3 stop_container.py")
        return 0
    if not confirm_headset():
        print("Not started. Run this again when the headset is ready.")
        return 0

    config = PreflightConfig.load(args.config)
    cmd = collection_command(args.conf, config)
    print(f"\nStarting data collection with {os.path.basename(args.conf)}.")
    print("Hold the button under your middle finger and move your hand to move the arm.")
    print("A = save trajectory, right joystick = discard. Ctrl+C here to stop.\n", flush=True)
    try:
        rc = subprocess.run(cmd, cwd=REPO_ROOT, env=session.compose_env(REPO_ROOT, config)).returncode
    except KeyboardInterrupt:
        rc = 130

    print("\nData collection ended.")
    print("Data is under", os.path.expanduser(config.dataset_root))
    print("When you are done for the day: python3 stop_container.py, then power the arm off\n"
          "and put the headset on its charger.")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
