"""Declarative description of what a correct WidowX setup looks like.

Everything the checks assert about the rig lives here rather than being
hard-coded in the check bodies, so that re-cabling the rig, swapping a camera
or adding a second arm is a config edit rather than a code edit.

The defaults below describe the LiraLab Alienware WidowX station as of the
``conf_jesse.py`` / RealSense D435 configuration. Override them by passing
``--config <file>`` (YAML if PyYAML is importable, JSON always).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from typing import List, Optional


@dataclasses.dataclass
class CameraSpec:
    """One camera the data collection config expects to be publishing."""

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
    usb_connector_chart: str = "usb_connector_chart.yml"

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
    def usb_cameras(self) -> List[CameraSpec]:
        return [c for c in self.cameras if c.kind == "usb"]

    @classmethod
    def from_dict(cls, data: dict) -> "PreflightConfig":
        data = dict(data)
        cams = data.pop("cameras", None)
        unknown = set(data) - {f.name for f in dataclasses.fields(cls)}
        if unknown:
            raise SystemExit(f"Unknown key(s) in preflight config: {', '.join(sorted(unknown))}")
        cfg = cls(**data)
        if cams is not None:
            cfg.cameras = [CameraSpec(**c) for c in cams]
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


def default_config() -> PreflightConfig:
    """The LiraLab WidowX station as currently cabled (RealSense D435 only).

    Matches ``widowx_envs/experiments/bridge_data_v2/conf_jesse.py``: one D435
    colour stream plus its aligned depth stream, no USB webcams. If you collect
    with a config that also uses the blue/yellow/wrist Logitechs, add them here
    (or in a ``--config`` override) so preflight actually checks them.
    """
    return PreflightConfig(
        cameras=[
            CameraSpec(
                name="D435",
                kind="realsense",
                image_topic="/D435/color/image_raw",
                info_topic="/D435/color/camera_info",
                serial="146322077603",
                v4l2_name="Intel(R) RealSense(TM) Depth Ca",
                width=640,
                height=480,
                required=True,
            ),
            CameraSpec(
                name="D435_depth",
                kind="realsense",
                image_topic="/D435/depth/image_rect_raw",
                info_topic="/D435/depth/camera_info",
                serial="146322077603",
                width=640,
                height=480,
                required=True,
            ),
        ]
    )
