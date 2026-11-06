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

End the session from the headset (right joystick, then A); the script then
offers to stop the container (stop_container.py). Ctrl+C also stops collection.

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


# From widowx_envs/widowx_env.py (VR_WidowX) and policies/vr_teleop_policy.py.
# Everything is on the RIGHT controller.
CONTROLS = """
================  VR CONTROLS (right controller)  ================
 Grip button (middle finger)
   - Press to START recording a trajectory.
   - HOLD it to move the arm: the arm follows your hand, position
     and rotation (wrist turns with your hand). Release it and the
     arm stops; move your hand freely, press again to continue from
     there (like lifting a mouse off the table).
 Trigger (index finger)
   - Closes the gripper; how far you pull = how closed it is.
     Release to open.
 B button
   - Before recording: moves the arm to its neutral pose.
   - While recording: ENDS the trajectory.
 After each trajectory:
   - A button               = SAVE it
   - Press the right joystick = DISCARD it
 End the session (while waiting to start the next trajectory):
   - Press the right joystick, then A to confirm
     (or the grip button to keep collecting).
 Notes
   - A trajectory also ends by itself after the conf's time limit.
   - Move smoothly. A sudden jump prints "delta transform too
     large!" and pauses in this terminal: type c and press Enter.
   - Ctrl+C in this terminal stops data collection.
=================================================================
"""


def controls_card(conf_path=None) -> str:
    """The controls card, plus which axes this conf locks (if it uses make_config)."""
    card = CONTROLS
    if not conf_path or not os.path.exists(conf_path):
        return card
    try:
        from widowx_envs.preflight.config import read_make_config
        from widowx_envs.simple_conf import describe_control, resolve_control
        mc = read_make_config(conf_path)
        if not mc or "action_mode" in mc.get("_not_literal", []):
            return card
        control, errors = resolve_control(mc.get("action_mode"), mc.get("control"))
    except Exception:
        return card
    if errors or not control:
        return card
    locked = describe_control(control)
    lines = [f" This conf ({os.path.basename(conf_path)}, action_mode={mc.get('action_mode')}):"]
    if locked:
        lines += [f"   - {l}" for l in locked]
    else:
        lines.append("   - every axis follows your hand")
    return card.rstrip("=\n") + "\n" + "\n".join(lines) + "\n" + "=" * 65 + "\n"


CONTROLS_WINDOW_PID = os.path.expanduser("~/.cache/widowx_preflight/controls_window.pid")


def open_controls_window(conf_path=None):
    """Show the controls card in its own window, to keep in view while collecting."""
    conf_arg = f" {session._sh(os.path.abspath(conf_path))}" if conf_path else ""
    inner = (
        f"python3 {session._sh(os.path.abspath(__file__))} --controls{conf_arg}; "
        "echo 'This window closes when data collection ends.'; read -r -p ''"
    )
    return session.open_window("WidowX VR controls", inner, CONTROLS_WINDOW_PID, REPO_ROOT,
                               size="68x40")


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
    p.add_argument("--controls", action="store_true", help="only print the VR controls and exit")
    p.add_argument("-y", "--yes", action="store_true",
                   help="do not ask whether to start collecting (the headset confirmation is still asked)")
    if "--controls" in sys.argv[1:]:
        rest = [a for a in sys.argv[1:] if a != "--controls" and not a.startswith("-")]
        print(controls_card(rest[0] if rest else None))
        return 0
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
    window = open_controls_window(args.conf)
    if window:
        print("\nThe VR controls are in a separate 'WidowX VR controls' window.")
    else:
        print(controls_card(args.conf))  # no desktop to open a window on
    print(f"Starting data collection with {os.path.basename(args.conf)}.\n", flush=True)
    try:
        rc = subprocess.run(cmd, cwd=REPO_ROOT, env=session.compose_env(REPO_ROOT, config)).returncode
    except KeyboardInterrupt:
        rc = 130
    finally:
        session.close_window(CONTROLS_WINDOW_PID)

    print("\nData collection ended.")
    print("Data is under", os.path.expanduser(config.dataset_root))
    # Exit code 0 = ended cleanly (from the headset, or num_trajectories reached).
    # After Ctrl+C or an error, do not offer it: the operator may want to look first.
    if rc == 0 and ask("\nStop the robonet container now? "
                       "(the arm goes to its sleep pose first, and you confirm before it stops)"):
        stop_rc = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "stop_container.py")],
                                 cwd=REPO_ROOT).returncode
        if stop_rc == 0:
            print("Power the arm off and put the headset on its charger.")
        return stop_rc
    print("When you are done for the day: python3 stop_container.py, then power the arm off\n"
          "and put the headset on its charger.")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
