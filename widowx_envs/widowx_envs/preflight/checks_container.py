"""Container-side preflight checks (ROS).

These must run *inside* the ``robonet`` container, where ROS noetic, the
interbotix workspace and the widowx_envs venv are available::

    docker compose exec robonet bash -lic "python3 ~/widowx_envs/widowx_envs/preflight/preflight.py --scope container"

``preflight.py --scope all`` does that for you from the host and merges the two
reports.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sys
import traceback
from typing import List

from widowx_envs.preflight.core import CheckResult, Context, Status, check

# How long to wait for a single message before declaring a topic dead.
MESSAGE_TIMEOUT_S = 5.0


def _ok(name, summary, **details) -> CheckResult:
    return CheckResult(name, Status.PASS, summary, details=details)


def _warn(name, summary, remedy="", **details) -> CheckResult:
    return CheckResult(name, Status.WARN, summary, remedy=remedy, details=details)


def _fail(name, summary, remedy="", **details) -> CheckResult:
    return CheckResult(name, Status.FAIL, summary, remedy=remedy, details=details)


def _skip(name, summary) -> CheckResult:
    return CheckResult(name, Status.SKIP, summary)


def _rospy(ctx: Context):
    """Import rospy and bring up a throwaway node (once per process)."""
    if "rospy" not in ctx.cache:
        import rospy

        rospy.init_node("widowx_preflight", anonymous=True, disable_signals=True)
        ctx.cache["rospy"] = rospy
    return ctx.cache["rospy"]


def _topics(ctx: Context) -> List[str]:
    return ctx.cache.get("ros_topics", [])


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #


@check("container.env", scope="container")
def container_env(ctx: Context) -> CheckResult:
    """The environment variables the collection scripts read are set."""
    name = "container.env"
    missing = [v for v in ctx.config.container_env_vars if not os.environ.get(v)]
    if missing:
        return _fail(
            name,
            f"unset: {', '.join(missing)}",
            remedy="These are set by the Dockerfile and ~/.bashrc. You are probably in a\n"
            "non-login shell - use `docker compose exec robonet bash -lic '...'`\n"
            "(note the -l) rather than plain `bash -c`.",
        )
    arm = os.environ.get("ROBONETV2_ARM")
    if arm != ctx.config.arm_model:
        return _warn(
            name,
            f"ROBONETV2_ARM={arm} but config expects {ctx.config.arm_model}",
            remedy="Either fix the Dockerfile ENV or update arm_model in the preflight config.",
        )
    return _ok(name, ", ".join(f"{v}={os.environ[v]}" for v in ctx.config.container_env_vars))


def _culprit_package(exc: BaseException) -> str:
    """The installed package the failing line lives in, if any.

    Walks the traceback for the deepest frame under site-/dist-packages, so a
    TypeError raised inside e.g. gym is reported as "gym", not as our import.
    """
    culprit = ""
    tb = exc.__traceback__
    while tb is not None:
        path = tb.tb_frame.f_code.co_filename
        for marker in ("site-packages/", "dist-packages/"):
            if marker in path:
                culprit = path.split(marker, 1)[1].split("/", 1)[0]
        tb = tb.tb_next
    return culprit.split(".py")[0]


@check("container.python_env", scope="container")
def python_env(ctx: Context) -> List[CheckResult]:
    """The modules run_data_collection.py imports are importable."""
    results = []
    for mod in ("numpy", "scipy", "rospy", "cv_bridge", "multicam_server.topic_utils",
                "widowx_envs.widowx_env", "oculus_reader"):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            remedy = ""
            culprit = _culprit_package(exc)
            if "typeDict" in str(exc):
                remedy = (
                    "Known issue: old scipy against new numpy. Inside the container run\n"
                    "  pip install --upgrade scipy"
                )
            elif mod == "oculus_reader":
                remedy = "pip install git+https://github.com/rail-berkeley/oculus_reader.git"
            elif isinstance(exc, TypeError) and "not subscriptable" in str(exc) and culprit:
                py = f"{sys.version_info.major}.{sys.version_info.minor}"
                remedy = (
                    f"'{culprit}' uses syntax newer than this container's Python {py} (e.g.\n"
                    f"list[str]). The installed version dropped {py} support without saying so.\n"
                    f"Pin an older {culprit} in widowx_envs/requirements.txt and rebuild\n"
                    f"(preflight --build). Check what is installed: pip show {culprit}"
                )
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            results.append(
                _fail(
                    f"container.python_env.{mod}",
                    f"{type(exc).__name__}: {exc}" + (f" (in {culprit})" if culprit else ""),
                    remedy=remedy or "Traceback tail:\n" + "".join(tb[-4:]).rstrip(),
                    traceback="".join(tb),
                )
            )
        else:
            results.append(_ok(f"container.python_env.{mod}", "importable"))
    return results


@check("container.data_dir", scope="container")
def data_dir(ctx: Context) -> CheckResult:
    """$DATA is mounted and writable from inside the container."""
    name = "container.data_dir"
    path = os.environ.get("DATA")
    if not path:
        return _fail(name, "$DATA is unset", remedy="See container.env.")
    if not os.path.isdir(path):
        return _fail(
            name,
            f"{path} is not a directory",
            remedy=f"The {ctx.config.dataset_root} volume in docker-compose.yml is not mounted.\n"
            "Re-run preflight on the host (it creates the folder) and restart the container.",
        )
    probe = os.path.join(path, ".preflight_write_test")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as exc:
        return _fail(
            name,
            f"{path} is not writable: {exc}",
            remedy=f"On the host, check what is inside {ctx.config.dataset_root} (ls -la), then give it\n"
            f"to uid {ctx.config.container_uid}, e.g. sudo chown -R $(id -u):$(id -g) {ctx.config.dataset_root}\n"
            f"if your login user is uid {ctx.config.container_uid}. Then re-run preflight.",
        )
    return _ok(name, f"{path} writable")


# --------------------------------------------------------------------------- #
# ROS graph
# --------------------------------------------------------------------------- #


@check("container.ros_master", scope="container")
def ros_master(ctx: Context) -> CheckResult:
    """roscore is up and we can enumerate topics."""
    name = "container.ros_master"
    rc, out, err = ctx.run(["rostopic", "list"], timeout=20)
    if rc != 0:
        return _fail(
            name,
            "cannot reach the ROS master",
            remedy="The roslaunch in window 1 is not running. Start it on the host:\n"
            "  USB_CONNECTOR_CHART=$(pwd)/usb_connector_chart.yml docker compose up --build robonet",
            stderr=err.strip(),
        )
    topics = [t.strip() for t in out.splitlines() if t.strip()]
    ctx.cache["ros_topics"] = topics
    return _ok(name, f"{len(topics)} topics advertised", topic_count=len(topics))


@check("container.arm_node", scope="container", requires=["container.ros_master"])
def arm_node(ctx: Context) -> CheckResult:
    """The interbotix xs_sdk node is up and publishing joint states."""
    name = "container.arm_node"
    topic = ctx.config.arm_joint_states_topic
    if topic not in _topics(ctx):
        return _fail(
            name,
            f"{topic} is not advertised",
            remedy="The arm driver did not start. Check the roslaunch output for\n"
            "'Failed to open port' - usually the mini-USB cable or the arm's power.",
        )
    rospy = _rospy(ctx)
    from sensor_msgs.msg import JointState

    try:
        msg = rospy.wait_for_message(topic, JointState, timeout=MESSAGE_TIMEOUT_S)
    except Exception:
        return _fail(
            name,
            f"{topic} is advertised but no message arrived in {MESSAGE_TIMEOUT_S:.0f}s",
            remedy="The arm driver is wedged. Restart the robonet container, holding the\n"
            "arm so it does not drop when the torque disengages.",
        )
    return _ok(name, f"{len(msg.name)} joints reporting", joints=list(msg.name))


@check("container.camera_topics", scope="container", requires=["container.ros_master"])
def camera_topics(ctx: Context) -> List[CheckResult]:
    """Every configured camera publishes both image and camera_info."""
    results: List[CheckResult] = []
    topics = _topics(ctx)
    for cam in ctx.config.cameras:
        name = f"container.camera_topics.{cam.name}"
        missing = [t for t in (cam.image_topic, cam.info_topic) if t not in topics]
        if missing:
            status = _fail if cam.required else _warn
            if cam.kind == "realsense":
                remedy = (
                    "The realsense2_camera nodelet did not come up. Check the roslaunch\n"
                    "output for 'No RealSense devices were found!'. Verify the serial in\n"
                    f"widowx_rs.launch matches this camera ({cam.serial}), replug the D435\n"
                    "(prefer a USB 3 port), and make sure it is NOT also listed in\n"
                    "usb_connector_chart.yml."
                )
            else:
                remedy = (
                    f"multicam_server did not start a streamer for /{cam.name}. Check that\n"
                    f"usb_connector_chart.yml has a '{cam.chart_key or cam.name}' entry with a\n"
                    "non-empty USB path, then restart the container."
                )
            results.append(status(name, f"missing topic(s): {', '.join(missing)}", remedy=remedy))
            continue

        # camera_info specifically: CameraRecorder blocks on it forever.
        results.append(_check_camera_stream(ctx, cam, name))
    return results


def _check_camera_stream(ctx, cam, name) -> CheckResult:
    rospy = _rospy(ctx)
    from sensor_msgs.msg import Image

    try:
        first = rospy.wait_for_message(cam.image_topic, Image, timeout=MESSAGE_TIMEOUT_S)
    except Exception:
        return _fail(
            name,
            f"{cam.image_topic} is advertised but silent for {MESSAGE_TIMEOUT_S:.0f}s",
            remedy="The driver is advertising but not capturing. Unplug/replug the camera\n"
            "and restart the container.",
        )

    details = {
        "resolution": f"{first.width}x{first.height}",
        "encoding": first.encoding,
    }

    if (first.width, first.height) != (cam.width, cam.height):
        return _warn(
            name,
            f"publishing {first.width}x{first.height}, config expects {cam.width}x{cam.height}",
            remedy="Images get resized by IMTopic.process_image, but a mismatch usually means\n"
            "the driver fell back to a default mode. Check the launch file.",
            **details,
        )

    # Frozen-camera detection: CameraRecorder errors out after MAX_REPEATS
    # identical frames, but only mid-trajectory. Catch it here instead.
    try:
        second = rospy.wait_for_message(cam.image_topic, Image, timeout=MESSAGE_TIMEOUT_S)
    except Exception:
        second = None
    if second is not None:
        h1 = hashlib.md5(bytes(first.data)).hexdigest()
        h2 = hashlib.md5(bytes(second.data)).hexdigest()
        if h1 == h2:
            return _warn(
                name,
                "two consecutive frames are byte-identical (camera may be frozen)",
                remedy="If the scene was perfectly static this is harmless; otherwise the\n"
                "camera is stuck. Unplug/replug it and restart the container.",
                **details,
            )

    return _ok(name, f"{details['resolution']} {first.encoding}", **details)


@check("container.collection_config", scope="container", requires=["container.ros_master"])
def collection_config(ctx: Context) -> List[CheckResult]:
    """The experiment conf file's camera topics are actually live.

    Only runs when ``--conf <experiment file>`` is given. This is the check
    that matters most in practice: it validates the exact config you are about
    to hand to ``run_data_collection.py``, not a generic expectation.
    """
    name = "container.collection_config"
    conf_path = ctx.cache.get("conf_file")
    if not conf_path:
        return [_skip(name, "no --conf given")]
    if not os.path.exists(conf_path):
        return [_fail(name, f"{conf_path} does not exist")]

    try:
        spec = importlib.util.spec_from_file_location("preflight_hyperparams", conf_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = module.config
    except Exception as exc:
        return [
            _fail(
                name,
                f"could not import {os.path.basename(conf_path)}: {type(exc).__name__}: {exc}",
                remedy="run_data_collection.py imports this file the same way, so it would\n"
                "fail identically.",
            )
        ]

    results = [_ok(f"{name}.import", f"{os.path.basename(conf_path)} imports cleanly")]
    ctx.cache["conf_config"] = config  # for container.control_start

    # Short-form confs (simple_conf.make_config) carry the metadata inline.
    if "metadata" in config:
        from widowx_envs.simple_conf import REQUIRED_METADATA
        md = config["metadata"] or {}
        empty = [k for k in REQUIRED_METADATA if not str(md.get(k, "")).strip()]
        if empty:
            results.append(_fail(f"{name}.metadata", f"metadata needs {', '.join(empty)} filled in"))
        else:
            results.append(_ok(f"{name}.metadata",
                               ", ".join(f"{k}: {md[k]}" for k in REQUIRED_METADATA)))
    # run() asserts on this key before doing anything else.
    elif "collection_metadata" not in config:
        results.append(
            _fail(
                f"{name}.collection_metadata",
                "config has no 'collection_metadata' key",
                remedy="run_data_collection.py asserts on it. Point it at a metadata json,\n"
                "e.g. current_dir + '/collection_metadata.json'.",
            )
        )
    else:
        meta = config["collection_metadata"]
        if not os.path.exists(meta):
            results.append(
                _fail(f"{name}.collection_metadata", f"{meta} does not exist")
            )
        else:
            try:
                with open(meta) as f:
                    data = json.load(f)
            except Exception as exc:
                results.append(_fail(f"{name}.collection_metadata", f"{meta} is not valid json: {exc}"))
            else:
                if not data:
                    results.append(
                        _warn(
                            f"{name}.collection_metadata",
                            f"{meta} is empty",
                            remedy="Session metadata (teleoperator, task instruction) belongs here -\n"
                            "it is copied verbatim into the saved trajectory folder. Collecting\n"
                            "with an empty file means unlabelled data.",
                        )
                    )
                else:
                    results.append(
                        _ok(f"{name}.collection_metadata", ", ".join(sorted(data)))
                    )

    # Cross-check the conf's topics against the live graph.
    env_params = config.get("agent", {}).get("env", (None, {}))[1]
    live = set(_topics(ctx))
    declared = []
    for key in ("camera_topics", "depth_camera_topics"):
        for topic in env_params.get(key, []):
            declared.append(getattr(topic, "name", str(topic)))
    for topic in declared:
        if topic in live:
            results.append(_ok(f"{name}.topic{topic}", "live"))
        else:
            results.append(
                _fail(
                    f"{name}.topic{topic}",
                    "declared in the conf but not advertised",
                    remedy="Collection will hang in CameraRecorder waiting for this topic.\n"
                    "Fix the camera, or remove the topic from the conf file.",
                )
            )
    return results


@check("container.control_start", scope="container")
def control_start(ctx: Context) -> List[CheckResult]:
    """The start pose from the conf's fixed axes is reachable (IK + joint limits), without moving."""
    name = "container.control_start"
    config = ctx.cache.get("conf_config")
    if config is None:
        return [_skip(name, "no --conf given, or it did not import")]
    control = (config.get("policy") or {}).get("control")
    from widowx_envs.control_utils import fixed_axes, fixed_start_pose
    fixed = fixed_axes(control)
    if not fixed:
        return [_ok(name, "no fixed x/y/z/roll/pitch/yaw in the conf: nothing to move to")]

    import numpy as np
    import modern_robotics as mr
    import widowx_envs.utils.transformation_utils as tr
    from interbotix_xs_modules import mr_descriptions as mrd
    from widowx_controller.widowx_controller import DEFAULT_ROTATION, NEUTRAL_JOINT_STATE

    arm = ctx.config.arm_model
    robot = getattr(mrd, arm, None)
    if robot is None:
        return [_warn(name, f"no kinematic description for arm model {arm!r}; cannot check")]
    env_params = (config.get("agent") or {}).get("env", (None, {}))[1] or {}
    base_angle = env_params.get("workspace_rotation_angle_z", 0) or 0
    default_rot = np.dot(tr.eulerAnglesToRotationMatrix([0, 0, base_angle]), DEFAULT_ROTATION)

    # Same pose VR_WidowX moves to: neutral, with the fixed values swapped in.
    neutral = mr.FKinSpace(robot.M, robot.Slist, NEUTRAL_JOINT_STATE)
    target = fixed_start_pose(neutral, control, default_rot)
    where = ", ".join(f"{a}={v:g}" for a, v in fixed.items())

    # IK like the Interbotix arm interface: several initial guesses, wrap to (-pi, pi].
    waist = np.arctan2(target[1, 3], target[0, 3])
    guesses = [np.array(NEUTRAL_JOINT_STATE), np.zeros(len(NEUTRAL_JOINT_STATE)),
               np.concatenate([[waist], np.array(NEUTRAL_JOINT_STATE)[1:]])]
    solution = None
    for guess in guesses:
        theta, ok = mr.IKinSpace(robot.Slist, robot.M, target, guess, 0.001, 0.001)
        if ok:
            solution = (np.asarray(theta) + np.pi) % (2 * np.pi) - np.pi
            break
    if solution is None:
        return [_fail(
            name,
            f"the start pose for the fixed values ({where}) has no IK solution: the arm cannot reach it",
            remedy="Change those values in the conf (closer to the neutral pose), or use \"hold\"\n"
            "instead of a number. Collection would stop at the start of the first trajectory.",
        )]

    limits = _joint_limits(ctx, arm)
    if limits is None:
        return [_warn(name, f"start pose ({where}) is reachable by IK, but the joint limits could not be "
                      "read from the arm driver, so they were not checked")]
    names, lower, upper = limits
    bad = [f"{n} {np.rad2deg(q):.0f} deg (limits {np.rad2deg(lo):.0f}..{np.rad2deg(hi):.0f})"
           for n, q, lo, hi in zip(names, solution, lower, upper) if not lo - 1e-3 <= q <= hi + 1e-3]
    if bad:
        return [_fail(
            name,
            f"the start pose for the fixed values ({where}) needs joints beyond their limits: {'; '.join(bad)}",
            remedy="Change those values in the conf, or use \"hold\" instead of a number.",
        )]
    xyz = target[:3, 3]
    return [_ok(name, f"start pose reachable ({where}): x={xyz[0]:.3f} y={xyz[1]:.3f} z={xyz[2]:.3f} m, "
                      "within joint limits")]


def _joint_limits(ctx: Context, arm: str):
    """(names, lower, upper) of the arm group from the Interbotix driver, or None."""
    try:
        rospy = _rospy(ctx)
        from interbotix_xs_msgs.srv import RobotInfo
        srv = f"/{arm}/get_robot_info"
        rospy.wait_for_service(srv, timeout=5)
        info = rospy.ServiceProxy(srv, RobotInfo)(cmd_type="group", name="arm")
        return list(info.joint_names), list(info.joint_lower_limits), list(info.joint_upper_limits)
    except Exception:
        return None
