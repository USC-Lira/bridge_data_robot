"""Short experiment configs for WidowX data collection.

A project's conf file only states what differs between projects::

    from widowx_envs.simple_conf import make_config

    config = make_config(
        cameras=["D435"],
        depth=True,
        action_mode="3trans3rot",
        metadata={"task": "put the cup in the bowl", "operator": "Hugo"},
    )

``make_config`` fills in everything else with the values the hand-written
``conf_*.py`` files used, and returns the same ``config`` dict that
``run_data_collection.py`` expects.

The checks in this module are plain Python (no ROS), so preflight runs the
same ones on the host before anything starts: see ``check_settings``.
"""

import copy
import difflib
import math
import inspect
import os
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# cameras
# --------------------------------------------------------------------------- #

# Cameras driven by the realsense2_camera nodelet (widowx_rs.launch). The
# Alienware's is a D415 published under the historical name "D435".
REALSENSE_CAMERAS = ("D435",)
# USB webcams streamed by multicam_server via usb_connector_chart.yml.
USB_CAMERAS = ("blue", "yellow", "wrist")
KNOWN_CAMERAS = REALSENSE_CAMERAS + USB_CAMERAS


def camera_topic(name: str) -> str:
    if name in REALSENSE_CAMERAS:
        return f"/{name}/color/image_raw"
    return f"/{name}/image_raw"


def depth_topic(name: str) -> str:
    return f"/{name}/depth/image_rect_raw"


def topics_for(cameras: List[str], depth: bool) -> Dict[str, List[str]]:
    """The topics a make_config(...) call records, in read_conf_topics() form."""
    out = {"camera_topics": [camera_topic(c) for c in cameras]}
    if depth:
        out["depth_camera_topics"] = [depth_topic(c) for c in cameras if c in REALSENSE_CAMERAS]
    return out


# --------------------------------------------------------------------------- #
# control: which axes the operator moves
# --------------------------------------------------------------------------- #

AXES = ("x", "y", "z", "roll", "pitch", "yaw", "gripper")
POSITION_AXES = ("x", "y", "z")
ANGLE_AXES = ("roll", "pitch", "yaw")

# The old action modes, as presets. The robot always runs in 3trans3rot, so
# every dataset records the same 7-number actions; locked axes are recorded as
# "no change". Angles are degrees from the gripper's default orientation, so
# 0 is what the old modes did when they zeroed an angle.
_TELEOP_ALL = {a: "teleop" for a in AXES}
ACTION_MODE_PRESETS = {
    "3trans3rot": dict(_TELEOP_ALL),
    "3trans1rot": dict(_TELEOP_ALL, roll=0, pitch=0),
    "3trans": dict(_TELEOP_ALL, roll=0, pitch=0, yaw=0),
}
ACTION_MODES = tuple(ACTION_MODE_PRESETS) + ("custom",)


def resolve_control(action_mode, control) -> Tuple[Optional[Dict], List[str]]:
    """Return (control dict, errors) for an action_mode / control pair.

    action_mode is required. A preset ("3trans3rot", "3trans1rot", "3trans")
    defines the control itself and must not be combined with a control dict;
    "custom" requires one, with every axis set to "teleop", "hold" or a number
    (meters for x/y/z, degrees for roll/pitch/yaw, 0 closed .. 1 open for the
    gripper).
    """
    errors: List[str] = []
    if action_mode is None:
        return None, [f"action_mode is required: one of {', '.join(ACTION_MODES)}"]
    if action_mode not in ACTION_MODES:
        return None, [f"unknown action_mode {action_mode!r}: use one of {', '.join(ACTION_MODES)}"]

    if action_mode != "custom":
        if control is not None:
            errors.append(
                f"control is only used with action_mode='custom'; action_mode={action_mode!r} "
                "already defines it. Remove control, or set action_mode='custom'."
            )
        return dict(ACTION_MODE_PRESETS[action_mode]), errors

    if not isinstance(control, dict):
        return None, ["action_mode='custom' needs a control dict with every axis: " + ", ".join(AXES)]
    missing = [a for a in AXES if a not in control]
    unknown = [k for k in control if k not in AXES]
    if missing:
        errors.append(f"control is missing {', '.join(missing)} (all of {', '.join(AXES)} are required)")
    if unknown:
        errors.append(f"control has unknown axes {', '.join(map(str, unknown))} (use {', '.join(AXES)})")
    for axis in AXES:
        if axis not in control:
            continue
        v = control[axis]
        if v in ("teleop", "hold"):
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"control[{axis!r}] = {v!r}: use 'teleop', 'hold' or a number")
        elif axis == "gripper" and not 0 <= v <= 1:
            errors.append(f"control['gripper'] = {v}: must be between 0 (closed) and 1 (open)")
        elif axis in ANGLE_AXES and abs(v) > 180:
            errors.append(f"control[{axis!r}] = {v}: degrees, between -180 and 180")
    return (dict(control) if not errors else None), errors


# Rough reach of the wx250s, for a quick plain-Python sanity check of fixed
# positions (the exact check, with the real kinematics and joint limits, is
# preflight's container.control_start). Base frame: z = 0 at the base plate.
SHOULDER_HEIGHT_M = 0.11
MAX_REACH_M = 0.62  # from the shoulder; the wx250s is specified at ~0.65 m


def position_errors(control: Dict) -> List[str]:
    """Fixed x/y/z values that are clearly impossible for the arm."""
    fixed = {a: control[a] for a in POSITION_AXES
             if not isinstance(control.get(a), bool) and isinstance(control.get(a), (int, float))}
    if not fixed:
        return []
    errors = []
    if fixed.get("z", 1.0) < 0:
        errors.append(f"control['z'] = {fixed['z']} m is below the robot's base (z = 0 is the base plate)")
    if len(fixed) == 3:
        x, y, z = fixed["x"], fixed["y"], fixed["z"]
        reach = math.sqrt(x * x + y * y + (z - SHOULDER_HEIGHT_M) ** 2)
        if reach > MAX_REACH_M:
            errors.append(f"fixed position ({x}, {y}, {z}) is {reach:.2f} m from the shoulder; "
                          f"the arm reaches about {MAX_REACH_M} m")
    else:
        # Only some axes fixed: the others come from the neutral pose, which is at
        # about x=0.12, y=-0.02, z=0.25 (FK of NEUTRAL_JOINT_STATE for the wx250s).
        x, y, z = fixed.get("x", 0.12), fixed.get("y", -0.02), fixed.get("z", 0.25)
        reach = math.sqrt(x * x + y * y + (z - SHOULDER_HEIGHT_M) ** 2)
        if reach > MAX_REACH_M:
            errors.append(f"fixed {', '.join(f'{a}={v}' for a, v in fixed.items())} puts the start pose "
                          f"about {reach:.2f} m from the shoulder; the arm reaches about {MAX_REACH_M} m")
    return errors


def describe_control(control: Dict) -> List[str]:
    """Human-readable lines for the controls card, e.g. 'pitch: held'."""
    lines = []
    for axis in AXES:
        v = control.get(axis, "teleop")
        if v == "teleop":
            continue
        if v == "hold":
            lines.append(f"{axis}: held where it starts (does not follow your hand)")
        elif axis == "gripper":
            lines.append(f"gripper: fixed at {v:g} (0 closed, 1 open), the trigger does nothing")
        elif axis in ANGLE_AXES:
            lines.append(f"{axis}: fixed at {v:g} deg from the default orientation")
        else:
            lines.append(f"{axis}: fixed at {v:g} m")
    return lines


def angle_warnings(control: Dict) -> List[str]:
    """Fixed or held angles mixed with free ones are split into roll/pitch/yaw.

    Near +/-90 deg of pitch from the default orientation roll and yaw become
    ambiguous (gimbal lock), and a partly locked wrist can behave oddly there.
    """
    fixed = [a for a in ANGLE_AXES if control.get(a) != "teleop"]
    free = [a for a in ANGLE_AXES if control.get(a) == "teleop"]
    if fixed and free:
        return [
            f"{', '.join(fixed)} locked while {', '.join(free)} "
            f"{'follows' if len(free) == 1 else 'follow'} the hand: avoid tilting the "
            "gripper near 90 deg of pitch from its default orientation (gimbal lock)."
        ]
    return []


# --------------------------------------------------------------------------- #
# defaults: what every hand-written conf_*.py file had in common
# --------------------------------------------------------------------------- #

ENV_DEFAULTS = {
    "gripper_attached": "custom",
    "skip_move_to_neutral": False,
    "move_to_rand_start_freq": -1,
    "fix_zangle": 0.1,
    "move_duration": 0.2,
    "adaptive_wait": True,
    "action_clipping": None,
    # Always the full 7-number action space; locking happens in the teleop
    # policy (see control), so all datasets share one action format.
    "action_mode": "3trans3rot",
}
AGENT_DEFAULTS = {
    "recreate_env": (False, 1),
    "T": 500,
    "image_height": 480,
    "image_width": 640,
    "make_final_gif": False,
    "video_format": "mp4",
}
COLLECTION_DEFAULTS = {
    "start_index": 0,
    "end_index": 10 ** 9,  # no limit: stop from the headset (see the controls card)
    "save_format": ["raw"],
    "make_diagnostics": False,
    "record_floor_height": False,
}
REQUIRED_METADATA = ("task", "operator")
ENVIRONMENTS = ("vr", "intervention")


def _check_overrides(kind: str, overrides: Optional[dict], known: dict, extra_ok=()) -> List[str]:
    errors = []
    names = list(known) + list(extra_ok)
    for key in (overrides or {}):
        if key in names:
            continue
        close = difflib.get_close_matches(str(key), names, n=1)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        errors.append(f"unknown {kind} setting {key!r}.{hint}")
    return errors


# Settings the env classes accept beyond ENV_DEFAULTS, so overrides of them are
# not flagged as typos. From RobotBaseEnv / WidowXEnv default hparams.
EXTRA_ENV_SETTINGS = (
    "start_state", "continuous_gripper", "override_workspace_boundaries", "camera_topics",
    "depth_camera_topics", "image_crop_xywh", "num_task_stages", "make_oculus_reader",
)
EXTRA_AGENT_SETTINGS = ("imax", "ask_traj_ok", "make_partial_gif", "log_dir")


def check_settings(cameras=None, depth=False, action_mode=None, control=None, metadata=None,
                   environment="vr", num_trajectories=None, max_seconds_per_trajectory=None,
                   neutral_before_each=True, env=None, agent=None, collection=None, **unknown) -> Tuple[Optional[Dict], List[str], List[str]]:
    """Validate make_config() arguments. Returns (control, errors, warnings).

    Plain Python, so preflight runs exactly these checks on the host.
    """
    errors: List[str] = []
    warnings: List[str] = []
    for key in unknown:
        errors.append(f"make_config() got an unknown argument {key!r}")

    if not cameras:
        errors.append("cameras is required, e.g. cameras=['D435']")
    else:
        for c in cameras:
            if c not in KNOWN_CAMERAS:
                errors.append(f"unknown camera {c!r}: use {', '.join(KNOWN_CAMERAS)}")
        if len(set(cameras)) != len(cameras):
            errors.append("cameras lists the same camera twice")
    if depth and cameras and not any(c in REALSENSE_CAMERAS for c in cameras):
        errors.append("depth=True needs a RealSense camera in cameras (" + ", ".join(REALSENSE_CAMERAS) + ")")

    resolved, control_errors = resolve_control(action_mode, control)
    errors += control_errors
    if resolved:
        errors += position_errors(resolved)
        warnings += angle_warnings(resolved)
        if any(isinstance(resolved[a], (int, float)) and not isinstance(resolved[a], bool)
               for a in POSITION_AXES):
            warnings.append("a fixed x/y/z is an absolute position in the robot's base frame: before "
                            "each trajectory the arm moves there slowly (5 cm/s) from neutral; make "
                            "sure that path is clear.")

    if not isinstance(metadata, dict):
        errors.append("metadata is required, e.g. metadata={'task': '...', 'operator': '...'}")
    else:
        empty = [k for k in REQUIRED_METADATA if not str(metadata.get(k, "")).strip()]
        if empty:
            errors.append(f"metadata needs {', '.join(empty)} filled in")

    if not isinstance(neutral_before_each, bool):
        errors.append("neutral_before_each must be True or False")
    if environment not in ENVIRONMENTS:
        errors.append(f"environment={environment!r}: use one of {', '.join(ENVIRONMENTS)}")
    if num_trajectories is not None and (not isinstance(num_trajectories, int) or num_trajectories < 1):
        errors.append("num_trajectories must be a positive whole number, or left out for no limit")
    if max_seconds_per_trajectory is not None and not (
            isinstance(max_seconds_per_trajectory, (int, float)) and max_seconds_per_trajectory > 0):
        errors.append("max_seconds_per_trajectory must be a positive number of seconds")

    errors += _check_overrides("env", env, ENV_DEFAULTS, EXTRA_ENV_SETTINGS)
    errors += _check_overrides("agent", agent, AGENT_DEFAULTS, EXTRA_AGENT_SETTINGS)
    errors += _check_overrides("collection", collection, COLLECTION_DEFAULTS)
    if env and "action_mode" in env:
        errors.append("set action_mode with make_config(action_mode=...), not in env: the robot always "
                      "runs in 3trans3rot and locking happens in the teleop policy")
    return resolved, errors, warnings


# --------------------------------------------------------------------------- #
# the config itself (runs in the container: imports ROS-side classes)
# --------------------------------------------------------------------------- #


class ConfError(ValueError):
    pass


def make_config(cameras, action_mode, metadata, depth=False, control=None, environment="vr",
                num_trajectories=None, max_seconds_per_trajectory=100, neutral_before_each=True,
                env=None, agent=None, collection=None):
    """Build the config dict run_data_collection.py expects.

    Required: cameras, action_mode (+ control if 'custom'), metadata (task,
    operator). Everything else has the defaults the hand-written conf files
    used; env / agent / collection override any individual setting.
    """
    resolved, errors, warnings = check_settings(
        cameras=cameras, depth=depth, action_mode=action_mode, control=control, metadata=metadata,
        environment=environment, num_trajectories=num_trajectories,
        max_seconds_per_trajectory=max_seconds_per_trajectory, neutral_before_each=neutral_before_each,
        env=env, agent=agent, collection=collection,
    )
    if errors:
        raise ConfError("invalid experiment config:\n  - " + "\n  - ".join(errors))
    for w in warnings:
        print(f"[config] warning: {w}")

    from multicam_server.topic_utils import IMTopic
    from widowx_envs.control_loops import TimedLoop
    from widowx_envs.policies.vr_teleop_policy import VRTeleopPolicy

    if environment == "intervention":
        from widowx_envs.widowx_intervention_env import InterventionWidowX as env_class
    else:
        from widowx_envs.widowx_env import VR_WidowX as env_class

    topics = topics_for(cameras, depth)
    env_params = dict(copy.deepcopy(ENV_DEFAULTS))
    env_params["skip_move_to_neutral"] = not neutral_before_each
    # The env moves slowly to the fixed axes before each trajectory.
    env_params["control"] = resolved
    env_params["camera_topics"] = [IMTopic(t) for t in topics["camera_topics"]]
    if topics.get("depth_camera_topics"):
        env_params["depth_camera_topics"] = [IMTopic(t, dtype="16UC1") for t in topics["depth_camera_topics"]]
    env_params.update(env or {})

    agent_params = dict(copy.deepcopy(AGENT_DEFAULTS))
    if max_seconds_per_trajectory:
        agent_params["T"] = max(1, int(round(max_seconds_per_trajectory / env_params["move_duration"])))
    agent_params.update(agent or {})
    agent_params["type"] = TimedLoop
    agent_params["env"] = (env_class, env_params)

    # The conf file that called us: run_data_collection.py names the data
    # folder after its location (e.g. bridge_data_v2).
    caller = inspect.stack()[1].filename
    current_dir = os.path.dirname(os.path.realpath(caller))
    config = dict(copy.deepcopy(COLLECTION_DEFAULTS))
    if num_trajectories:
        config["end_index"] = num_trajectories - 1
    config.update(collection or {})
    # Recorded with every session (run_data_collection.py writes it next to
    # the trajectories), together with how the arm was controlled.
    full_metadata = dict(metadata)
    full_metadata.update({
        "action_mode": action_mode,
        "control": resolved,
        "cameras": list(cameras),
        "depth": bool(depth),
        "action_format": "xyz (m) + roll/pitch/yaw (rad) deltas + gripper (0 closed .. 1 open)",
    })
    config.update({
        "current_dir": current_dir,
        "metadata": full_metadata,
        "agent": agent_params,
        "policy": {"type": VRTeleopPolicy, "control": resolved},
    })
    return config
