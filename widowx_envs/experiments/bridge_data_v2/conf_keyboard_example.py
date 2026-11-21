"""Data collection with the keyboard instead of the VR headset.

Keys are typed in the collection terminal. The default layout is in
widowx_envs/widowx_envs/teleop_profiles.py; keyboard_profile_example.yaml
shows how to change some keys and the speeds. Run it with:

    python3 datacollection.py configs/conf_keyboard_example.py --preflight
"""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["blue", "yellow"],
    action_mode="3trans1rot",            # position + yaw is easiest to drive from a keyboard
    teleop="keyboard",
    # teleop_profile="keyboard_profile_example.yaml",   # optional: your own keys / speeds
    metadata={
        "task": "",                      # fill in
        "operator": "",                  # fill in
    },
)
