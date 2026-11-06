"""Data collection config: intervention environment, position-only control, blue webcam.

Uses InterventionWidowX (press A to close the gripper on an object before
recording). Its own waiting loop has no "end session" button: stop with Ctrl+C.
Actions are now recorded in the common 7-number format (rotation deltas are 0);
sessions recorded before this change used 4 numbers.
"""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["blue"],
    action_mode="3trans",        # roll, pitch, yaw fixed at the default orientation
    environment="intervention",
    metadata={"task": "", "operator": ""},
    neutral_before_each=True,
    env={"start_state": [0.3, 0.0, 0.15, 0, 0, 0, 1]},
)
