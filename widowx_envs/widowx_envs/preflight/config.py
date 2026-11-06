"""Declarative description of what a correct WidowX setup looks like.

Everything the checks assert about the rig lives here rather than being
hard-coded in the check bodies, so that re-cabling the rig, swapping a camera
or adding a second arm is a config edit rather than a code edit.

The defaults below describe the LiraLab Alienware WidowX station as of the
``conf_jesse.py`` / RealSense D435 configuration. Override them by passing
``--config <file>`` (YAML if PyYAML is importable, JSON always).

Cameras come in two lists:

* ``camera_catalog``: every camera the rig *could* have and how to find it
  (driver, v4l2 name, serial, topics). Written once per rig.
* ``cameras``: the ones this session needs. When ``--conf`` is given they are
  picked from the catalog by the topics the experiment conf records (see
  :func:`select_cameras_from_conf`), so the two never drift apart. Without
  ``--conf`` the defaults below apply.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import sys
from typing import Dict, List, Optional, Tuple


@dataclasses.dataclass
class CameraSpec:
    """One camera stream: how to find it, and whether this session needs it."""

    name: str
    # "realsense" cameras are driven by the realsense2_camera nodelet;
    # "usb" cameras are driven by multicam_server/start_streamers.py via the
    # usb connector chart.
    kind: str = "usb"
    image_topic: str = ""
    info_topic: str = ""
    # Only meaningful for kind == "realsense".
    serial: Optional[str] = None
    # Only meaningful for kind == "usb": the key this camera has in
    # usb_connector_chart.yml, and the substring that identifies it in
    # `v4l2-ctl --list-devices`.
    chart_key: Optional[str] = None
    v4l2_name: Optional[str] = None
    width: int = 640
    height: int = 480
    required: bool = True

    def __post_init__(self):
        if not self.image_topic:
            self.image_topic = f"/{self.name}/image_raw"
        if not self.info_topic:
            # Mirrors CameraRecorder's guess: the sibling "camera_info" of the
            # image topic. If that guess is wrong the recorder hangs forever in
            # rospy.wait_for_message, which is exactly what we want to catch.
            self.info_topic = os.path.join(os.path.split(self.image_topic)[0], "camera_info")


@dataclasses.dataclass
class PreflightConfig:
    robot: str = "widowx"

    # -- arm ---------------------------------------------------------------- #
    arm_model: str = "wx250s"
    # Created by the Interbotix udev rules for the U2D2 / mini-USB link.
    arm_serial_port: str = "/dev/ttyDXL"
    arm_joint_states_topic: str = "/wx250s/joint_states"

    # -- cameras ------------------------------------------------------------ #
    cameras: List[CameraSpec] = dataclasses.field(default_factory=list)
    # Every camera the rig could have. Entries in ``cameras`` are added to it
    # automatically, so a --config that only lists ``cameras`` still works.
    camera_catalog: List[CameraSpec] = dataclasses.field(default_factory=list)
    usb_connector_chart: str = "usb_connector_chart.yml"
    # Re-run generate_usb_config.sh on every preflight so the chart always
    # matches what is plugged in. Turn off (or pass --no-generate) if you keep
    # a hand-edited chart.
    generate_usb_chart: bool = True

    # -- teleop ------------------------------------------------------------- #
    # The Meta Quest 2 running the RAIL Oculus Teleoperation app, over adb.
    require_vr_headset: bool = True

    # -- data --------------------------------------------------------------- #
    # Target of the cross-robot layout: /datasets/<task_instruction>/<timestamp>.
    dataset_root: str = "/datasets"
    # Where this repo actually writes today (host side of the $DATA mount).
    legacy_dataset_root: str = "~/widowx_data"
    min_free_gb: float = 50.0
    # uid:gid the container writes as; the host dir must be owned by it.
    container_uid: int = 1000
    container_gid: int = 1002

    # -- container ---------------------------------------------------------- #
    compose_service: str = "robonet"
    container_env_vars: List[str] = dataclasses.field(
        default_factory=lambda: ["DATA", "EXP", "ROBONETV2_ARM"]
    )
    require_nvidia_runtime: bool = True

    # ----------------------------------------------------------------------- #

    def camera(self, name: str) -> Optional[CameraSpec]:
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    @property
    def realsense_cameras(self) -> List[CameraSpec]:
        return [c for c in self.cameras if c.kind == "realsense"]

    @property
    def catalog(self) -> List[CameraSpec]:
        """``camera_catalog`` plus anything in ``cameras`` it does not already have."""
        known = {c.image_topic for c in self.camera_catalog}
        return list(self.camera_catalog) + [c for c in self.cameras if c.image_topic not in known]

    @property
    def usb_cameras(self) -> List[CameraSpec]:
        return [c for c in self.cameras if c.kind == "usb"]

    @classmethod
    def from_dict(cls, data: dict) -> "PreflightConfig":
        data = dict(data)
        cams = data.pop("cameras", None)
        catalog = data.pop("camera_catalog", None)
        unknown = set(data) - {f.name for f in dataclasses.fields(cls)}
        if unknown:
            raise SystemExit(f"Unknown key(s) in preflight config: {', '.join(sorted(unknown))}")
        cfg = cls(**data)
        defaults = default_config()
        cfg.cameras = [CameraSpec(**c) for c in cams] if cams is not None else defaults.cameras
        cfg.camera_catalog = (
            [CameraSpec(**c) for c in catalog] if catalog is not None else defaults.camera_catalog
        )
        return cfg

    @classmethod
    def load(cls, path: Optional[str]) -> "PreflightConfig":
        if path is None:
            return default_config()
        path = os.path.expanduser(path)
        with open(path) as f:
            text = f.read()
        if path.endswith(".json"):
            return cls.from_dict(json.loads(text))
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit(
                f"Cannot read {path}: PyYAML is not installed for {sys.executable}.\n"
                "Install it (`sudo apt install python3-yaml`) or use a .json config."
            ) from exc
        return cls.from_dict(yaml.safe_load(text))

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _d435(name, image_topic, info_topic, v4l2_name=None) -> CameraSpec:
    return CameraSpec(
        name=name,
        kind="realsense",
        image_topic=image_topic,
        info_topic=info_topic,
        # The RealSense on the Alienware is a D415 (it replaced the D435
        # 146322077603); the "D435" names and topics are kept for compatibility
        # with the conf files. Must match REALSENSE_SERIAL in docker-compose.yml.
        serial="217222067236",
        v4l2_name=v4l2_name,
        width=640,
        height=480,
        required=True,
    )


def default_catalog() -> List[CameraSpec]:
    """Every camera the LiraLab WidowX station has had attached.

    The two Logitechs (blue, yellow) report the same v4l2 name; the usb
    connector chart is what tells them apart.
    """
    return [
        _d435("D435", "/D435/color/image_raw", "/D435/color/camera_info",
              v4l2_name="Intel(R) RealSense(TM) Depth Ca"),
        # Same physical device as D435, so no v4l2_name: it is enumerated once.
        _d435("D435_depth", "/D435/depth/image_rect_raw", "/D435/depth/camera_info"),
        CameraSpec(name="blue", kind="usb", chart_key="blue", v4l2_name="1080P Pro Stream"),
        CameraSpec(name="yellow", kind="usb", chart_key="yellow", v4l2_name="1080P Pro Stream"),
        CameraSpec(name="wrist", kind="usb", chart_key="wrist", v4l2_name="Piwebcam: UVC Camera"),
    ]


def default_config() -> PreflightConfig:
    """The LiraLab WidowX station as currently cabled (RealSense D435 only).

    ``cameras`` matches ``conf_jesse.py``: one D435 colour stream plus its
    aligned depth stream, no USB webcams. It only applies when no ``--conf`` is
    given; with ``--conf`` the cameras are picked from the catalog instead.
    """
    catalog = default_catalog()
    return PreflightConfig(
        cameras=[c for c in catalog if c.name in ("D435", "D435_depth")],
        camera_catalog=catalog,
    )


# --------------------------------------------------------------------------- #
# experiment conf -> cameras
# --------------------------------------------------------------------------- #

CONF_TOPIC_KEYS = ("camera_topics", "depth_camera_topics")


def read_conf_topics(path: str) -> Dict[str, List[str]]:
    """The topics a ``conf_*.py`` records, read without executing it.

    The conf files import ROS (``IMTopic``, ``VR_WidowX``), which the host's
    system python does not have, so this parses the source instead and pulls
    the first argument (or ``name=``) out of each ``IMTopic(...)`` in the
    ``camera_topics`` / ``depth_camera_topics`` lists. Commented-out topics are
    ignored for free. Raises ``ValueError`` if the file cannot be parsed.
    """
    with open(path) as f:
        source = f.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise ValueError(f"syntax error at line {exc.lineno}: {exc.msg}") from exc

    found: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value in CONF_TOPIC_KEYS):
                continue
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            topics = found.setdefault(key.value, [])
            for elt in value.elts:
                topic = _imtopic_name(elt)
                if topic is not None:
                    topics.append(topic)
    return found


def _imtopic_name(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.Call):
        return None
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    for kw in node.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def select_cameras_from_conf(
    config: PreflightConfig, topics: Dict[str, List[str]]
) -> Tuple[List[CameraSpec], List[str]]:
    """Pick the catalog cameras whose image topic the conf records.

    Returns ``(cameras, unknown_topics)``. Every selected camera is required:
    the conf records it, so collection hangs without it.
    """
    by_topic = {c.image_topic: c for c in config.catalog}
    cameras: List[CameraSpec] = []
    unknown: List[str] = []
    for key in CONF_TOPIC_KEYS:
        for topic in topics.get(key, []):
            spec = by_topic.get(topic)
            if spec is None:
                unknown.append(topic)
            elif spec not in cameras:
                cameras.append(dataclasses.replace(spec, required=True))
    return cameras, unknown
