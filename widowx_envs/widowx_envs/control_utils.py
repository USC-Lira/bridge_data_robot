"""Pose math for per-axis control (simple_conf.make_config's ``control``).

Shared by VR_WidowX (which moves to the start pose before recording) and
preflight's container check (which verifies the arm can reach it), so both
use exactly the same pose. Needs numpy; no ROS.
"""

import numpy as np

import widowx_envs.utils.transformation_utils as tr

POSITION_AXES = ("x", "y", "z")
ANGLE_AXES = ("roll", "pitch", "yaw")

START_SPEED_M_S = 0.05      # 5 cm/s
START_SPEED_RAD_S = 0.5     # ~30 deg/s
START_MIN_DURATION_S = 2.0


def fixed_axes(control):
    """{axis: value} for the axes the conf fixes to a number (gripper excluded)."""
    if not control:
        return {}
    return {a: float(v) for a, v in control.items()
            if a != "gripper" and v not in ("teleop", "hold")}


def fixed_start_pose(current_pose, control, default_rot):
    """``current_pose`` with the fixed x/y/z/roll/pitch/yaw values swapped in, or None.

    Angles are degrees from ``default_rot`` (the gripper's default orientation).
    """
    fixed = fixed_axes(control)
    if not fixed:
        return None
    rot, xyz = tr.TransToRp(current_pose)
    xyz = np.array(xyz, dtype=float)
    for i, axis in enumerate(POSITION_AXES):
        if axis in fixed:
            xyz[i] = fixed[axis]
    if any(a in fixed for a in ANGLE_AXES):
        euler = np.array(tr.rotationMatrixToEulerAngles(rot.dot(default_rot.transpose()),
                                                        check_error_thresh=1e-5), dtype=float)
        for i, axis in enumerate(ANGLE_AXES):
            if axis in fixed:
                euler[i] = np.deg2rad(fixed[axis])
        rot = tr.eulerAnglesToRotationMatrix(euler).dot(default_rot)
    return tr.RpToTrans(rot, xyz)


def start_move_duration(current_pose, target_pose):
    """Seconds for a slow, safe move between two poses."""
    dist = np.linalg.norm(target_pose[:3, 3] - current_pose[:3, 3])
    r = current_pose[:3, :3].T.dot(target_pose[:3, :3])
    angle = np.arccos(np.clip((np.trace(r) - 1) / 2, -1.0, 1.0))
    return max(START_MIN_DURATION_S, dist / START_SPEED_M_S, angle / START_SPEED_RAD_S)
