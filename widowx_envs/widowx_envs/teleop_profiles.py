"""Controls profiles: which key does what, for keyboard teleoperation.

A profile maps actions to keys, like a game's controller settings. The default
profile is below; a project can give its own file (YAML or JSON) that changes
only some of them:

    # my_keys.yaml
    bindings:
      z+: e          # up on E instead of Z
      gripper_toggle: g
    linear_speed_m_s: 0.02

and use it with make_config(teleop="keyboard", teleop_profile="my_keys.yaml").

Plain Python (PyYAML only for .yaml files), so preflight checks profiles on
the host with the same rules the keyboard device uses.
"""

import copy
import json
import os

# Key names: a single character, or one of these.
NAMED_KEYS = ("space", "enter", "esc", "backspace", "tab", "up", "down", "left", "right")

# Actions, grouped by when they are used. A key may appear in several phases
# (Enter starts a trajectory and also ends it), but not twice in one phase.
PHASES = {
    "waiting": ("start", "neutral", "end_session"),
    "recording": ("x+", "x-", "y+", "y-", "z+", "z-",
                  "roll+", "roll-", "pitch+", "pitch-", "yaw+", "yaw-",
                  "gripper_toggle", "gripper_close", "gripper_open",
                  "faster", "slower", "end_trajectory"),
    "reviewing": ("save", "discard"),
    "confirming": ("confirm", "cancel"),
}
ACTIONS = tuple(a for actions in PHASES.values() for a in actions)
MOTION_ACTIONS = PHASES["recording"][:12]

DESCRIPTIONS = {
    "x+": "move forward", "x-": "move back", "y+": "move left", "y-": "move right",
    "z+": "move up", "z-": "move down",
    "roll+": "roll +", "roll-": "roll -", "pitch+": "pitch +", "pitch-": "pitch -",
    "yaw+": "yaw +", "yaw-": "yaw -",
    "gripper_toggle": "gripper open/closed", "gripper_close": "close gripper a step",
    "gripper_open": "open gripper a step",
    "faster": "faster", "slower": "slower",
    "start": "start recording", "end_trajectory": "end the trajectory",
    "neutral": "arm to neutral", "end_session": "end the session",
    "save": "save the trajectory", "discard": "discard the trajectory",
    "confirm": "yes (end the session)", "cancel": "no (keep collecting)",
}

# Motion layout as in widowx_envs/teleop.py.
DEFAULT_PROFILE = {
    "bindings": {
        "x+": "w", "x-": "s", "y+": "a", "y-": "d", "z+": "z", "z-": "c",
        "yaw+": "i", "yaw-": "k", "pitch+": "j", "pitch-": "l", "roll+": "n", "roll-": "m",
        "gripper_toggle": "space", "gripper_close": "[", "gripper_open": "]",
        "faster": "+", "slower": "-",
        "start": "enter", "end_trajectory": "enter",
        "neutral": "h", "end_session": "q",
        "save": "y", "discard": "x",
        "confirm": "y", "cancel": "n",
    },
    # Speeds while a key is held, at speed level 1.
    "linear_speed_m_s": 0.03,
    "angular_speed_deg_s": 15.0,
    # Multipliers that faster/slower step through, and the one to start at
    # (an index into speed_levels).
    "speed_levels": [0.5, 1.0, 2.0],
    "start_speed_level": 1,
    # How much gripper_close / gripper_open move it (0 closed .. 1 open).
    "gripper_step": 0.1,
}
SETTINGS = ("linear_speed_m_s", "angular_speed_deg_s", "speed_levels", "start_speed_level", "gripper_step")
# Upper limits, so a typo cannot make the arm fly.
MAX_LINEAR_M_S = 0.10
MAX_ANGULAR_DEG_S = 60.0


def resolve_path(path, base_dir=None):
    """A profile path as written in a conf: absolute, or relative to the conf's folder."""
    if os.path.isabs(path) or not base_dir:
        return path
    return os.path.join(base_dir, path)


def load_profile(path=None):
    """The default profile, with the file at ``path`` (if any) laid over it."""
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if not path:
        return profile
    with open(path) as f:
        text = f.read()
    if path.endswith(".json"):
        data = json.loads(text)
    else:
        import yaml  # only needed for .yaml profiles
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    unknown = [k for k in data if k not in ("bindings",) + SETTINGS]
    if unknown:
        raise ValueError(f"{path}: unknown setting(s) {', '.join(map(str, unknown))}")
    for key, value in data.items():
        if key == "bindings":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: bindings must be a mapping of action: key")
            profile["bindings"].update(value)
        else:
            profile[key] = value
    return profile


def _valid_key(key):
    return isinstance(key, str) and (len(key) == 1 or key in NAMED_KEYS)


def check_profile(profile):
    """List of problems with a profile (empty if it is fine)."""
    errors = []
    bindings = profile.get("bindings", {})
    for action, key in bindings.items():
        if action not in ACTIONS:
            errors.append(f"unknown action {action!r} (actions: {', '.join(ACTIONS)})")
        elif not _valid_key(key):
            errors.append(f"{action}: {key!r} is not a key (one character, or one of {', '.join(NAMED_KEYS)})")
    for action in ACTIONS:
        if action not in bindings:
            errors.append(f"no key for {action!r}")
    for phase, actions in PHASES.items():
        seen = {}
        for action in actions:
            key = bindings.get(action)
            if key is None:
                continue
            k = key.lower()
            if k in seen:
                errors.append(f"key {key!r} is used for both {seen[k]!r} and {action!r} ({phase})")
            seen[k] = action
    lin, ang = profile.get("linear_speed_m_s"), profile.get("angular_speed_deg_s")
    if not isinstance(lin, (int, float)) or not 0 < lin <= MAX_LINEAR_M_S:
        errors.append(f"linear_speed_m_s must be between 0 and {MAX_LINEAR_M_S}")
    if not isinstance(ang, (int, float)) or not 0 < ang <= MAX_ANGULAR_DEG_S:
        errors.append(f"angular_speed_deg_s must be between 0 and {MAX_ANGULAR_DEG_S}")
    levels = profile.get("speed_levels")
    if (not isinstance(levels, list) or not levels
            or not all(isinstance(v, (int, float)) and v > 0 for v in levels)):
        errors.append("speed_levels must be a list of positive numbers")
    elif isinstance(lin, (int, float)) and isinstance(ang, (int, float)):
        if lin * max(levels) > MAX_LINEAR_M_S or ang * max(levels) > MAX_ANGULAR_DEG_S:
            errors.append(f"the fastest speed level exceeds {MAX_LINEAR_M_S} m/s or {MAX_ANGULAR_DEG_S} deg/s")
        if not isinstance(profile.get("start_speed_level"), int) or not 0 <= profile["start_speed_level"] < len(levels):
            errors.append(f"start_speed_level must be an index into speed_levels (0..{len(levels) - 1})")
    step = profile.get("gripper_step")
    if not isinstance(step, (int, float)) or not 0 < step <= 1:
        errors.append("gripper_step must be between 0 and 1")
    return errors


def describe_profile(profile, control=None):
    """Lines for the controls card. Axes the conf locks are left out."""
    b = profile["bindings"]
    locked = set()
    for axis, value in (control or {}).items():
        if value != "teleop":
            locked.add(axis)

    def k(action):
        key = b[action]
        return key.upper() if len(key) == 1 and key.isalpha() else key

    lines = [" Hold a key to move; release it and the arm stops."]
    pairs = [("x", "forward / back"), ("y", "left / right"), ("z", "up / down"),
             ("yaw", "yaw"), ("pitch", "pitch"), ("roll", "roll")]
    for axis, what in pairs:
        if axis in locked:
            continue
        lines.append(f"   {k(axis + '+'):>6} / {k(axis + '-'):<6} {what}")
    if "gripper" not in locked:
        lines.append(f"   {k('gripper_toggle'):>15}  gripper open / closed")
        lines.append(f"   {k('gripper_close'):>6} / {k('gripper_open'):<6} close / open the gripper a step")
    lines.append(f"   {k('faster'):>6} / {k('slower'):<6} faster / slower")
    lines += [
        " Session:",
        f"   {k('start'):>6}  start recording      {k('end_trajectory'):>6}  end the trajectory",
        f"   {k('save'):>6}  save it              {k('discard'):>6}  discard it",
        f"   {k('neutral'):>6}  arm to neutral (before recording)",
        f"   {k('end_session'):>6}  end the session, then {k('confirm')} to confirm / {k('cancel')} to keep going",
    ]
    if locked:
        lines.append(" Locked by the conf (their keys do nothing): " + ", ".join(sorted(locked)))
    return lines
