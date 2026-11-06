"""Data collection config: yellow and blue webcams."""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["yellow", "blue"],
    action_mode="3trans3rot",
    metadata={"task": "", "operator": ""},
    neutral_before_each=False,
)
