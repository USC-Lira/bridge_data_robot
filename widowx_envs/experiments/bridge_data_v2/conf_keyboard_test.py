"""Keyboard test conf (Hugo): x/y and gripper by keyboard, z fixed, wrist held.

Based on conf_keyboard_example.py.

Keys are typed in the collection terminal. The default layout is in
widowx_envs/widowx_envs/teleop_profiles.py; keyboard_profile_example.yaml
shows how to change some keys and the speeds. Run it with:

    python3 datacollection.py widowx_envs/experiments/bridge_data_v2/conf_keyboard_test.py --preflight
"""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["blue", "yellow"],
    action_mode="custom",
    control={
        "x": "teleop", "y": "teleop", "z": 0.016,
        "roll": "hold", "pitch": "hold", "yaw": "hold",
        "gripper": "teleop",
    },
    teleop="keyboard",
    teleop_profile="keyboard_profile_example.yaml",
    metadata={
        "task": "keyboard test",
        "operator": "Hugo",
    },
)
