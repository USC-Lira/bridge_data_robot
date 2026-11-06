"""Data collection config: RealSense colour + depth, full 6-DoF teleop.

Only what differs between projects is set here; everything else uses the
defaults in widowx_envs/simple_conf.py. Run it with:

    python3 datacollection.py widowx_envs/experiments/bridge_data_v2/conf_jesse.py
"""
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["D435"],            # D435 (the RealSense), blue, yellow, wrist
    depth=True,                  # also record RealSense depth
    action_mode="3trans3rot",    # 3trans3rot, 3trans1rot, 3trans, or custom (+ control={...})
    metadata={
        "task": "",              # what the operator is asked to do, e.g. "put the cup in the bowl"
        "operator": "",          # who is collecting
    },
    neutral_before_each=True,    # arm returns to neutral before every trajectory
    # num_trajectories=50,       # optional: stop after this many (default: until you end it from the headset)
    # max_seconds_per_trajectory=100,
    # env={...}, agent={...}, collection={...}  # override any other setting, see simple_conf.py
)
