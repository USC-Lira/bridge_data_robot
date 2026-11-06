"""Data collection config: RealSense (colour + depth) plus the blue and wrist webcams."""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["D435", "blue", "wrist"],
    depth=True,
    action_mode="3trans3rot",
    metadata={"task": "", "operator": ""},
    neutral_before_each=False,
)
