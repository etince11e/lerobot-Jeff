#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import math
from dataclasses import dataclass, field
from pathlib import Path

from lerobot.cameras import CameraConfig, Cv2Backends
from lerobot.cameras.opencv import OpenCVCameraConfig

from ..config import RobotConfig


@dataclass
class RebotRSFollowerConfig:
    """Configuration for the reBot RS follower driven by reBotArm_control_py."""

    # Optional path to the reBotArm_control_py repository or installed package root.
    # When omitted, normal Python imports are tried first, followed by common sibling
    # repository locations used in this workspace.
    sdk_path: Path | None = None

    # Hardware YAML understood by reBotArm_control_py. Use None to let the SDK load
    # its config/rebotarm.yaml, which currently points at rebotarm_rs.yaml.
    hw_yaml: str | None = None

    # Arm control mode used by the SDK JointGroup.
    # Use RobStride MIT position/velocity/torque control for all arm joints.
    # ``posvel`` remains accepted by the follower for explicit compatibility,
    # but MIT is the safe/default path for this reBot RS teleoperation setup.
    arm_control_mode: str = "mit"

    # MIT gravity feed-forward. The value is multiplied by the Pinocchio
    # gravity torque vector before it is sent as the MIT ``tau`` term.
    gravity_compensation_enabled: bool = True
    gravity_compensation_scale: float = 1.0

    # SDK loop rates.  These are explicit here so the LeRobot teleoperation
    # command does not silently inherit an unnecessarily high rate from the
    # hardware YAML.  In MIT mode, Type-2 replies update the RX cache and the
    # periodic feedback sweep is disabled; feedback_rate_hz remains relevant
    # to the POS_VEL compatibility path and explicit SDK diagnostics.
    # Set either value to None to use the SDK YAML default.
    control_rate_hz: float | None = 500.0
    feedback_rate_hz: float | None = 10.0

    # IK solver parameters.
    ik_max_iter: int = 200
    ik_tolerance: float = 1e-4
    ik_step_size: float = 0.5
    ik_damping: float = 1e-6

    # Time constant for the continuous-velocity latest-target filter. This is
    # not a queued trajectory: a new IK target replaces the old target while
    # the command velocity is kept continuous. Set to 0 to bypass smoothing.
    joint_target_interpolation_time_s: float = 0.03

    # Cached hardware feedback older than this is reported as stale. Startup,
    # homing and settle checks still request synchronous feedback explicitly.
    feedback_max_age_s: float = 0.5

    # Optional low-rate diagnostic comparing the MotorBridge Type-2/RX cache
    # with a synchronous RobStride ``mechPos`` (0x7019) read.  This is
    # intentionally opt-in because each comparison performs one CAN query.
    position_compare_enabled: bool = False
    position_compare_motor_name: str = "joint1"
    position_compare_interval_s: float = 1.0
    position_compare_timeout_ms: int = 100

    # Pico trigger action is [0, 1]. This maps it to a gripper joint target in rad.
    gripper_open_pos: float = 4.71
    gripper_closed_pos: float = 0.0

    # Start pose used when teleoperation begins and when A-button homing returns.
    # Joint order: joint1..joint6, gripper.
    start_position: list[float] = field(
        default_factory=lambda: [0.0163, 0.6469, 0.5653, -0.5734, 0.0225, 0.0290, 4.7]
    )

    # Mechanical home pose used on Ctrl-C shutdown.
    home_position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # cameras
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    # Convenience slots for the common scene cameras. These default to the bench
    # cameras and are merged into ``cameras`` as ``head`` / ``wrist`` so the
    # observation schema and Rerun display pick them up automatically.
    head_camera: CameraConfig | None = field(
        default_factory=lambda: OpenCVCameraConfig(
            index_or_path=Path("/dev/video5"),
            width=640,
            height=480,
            fps=30,
            fourcc="MJPG",
            backend=Cv2Backends.V4L2,
        )
    )
    wrist_camera: CameraConfig | None = field(
        default_factory=lambda: OpenCVCameraConfig(
            index_or_path=Path("/dev/video2"),
            width=640,
            height=480,
            fps=30,
            fourcc="MJPG",
            backend=Cv2Backends.V4L2,
        )
    )

    def __post_init__(self):
        if self.head_camera is not None:
            self.cameras.setdefault("head", self.head_camera)
        if self.wrist_camera is not None:
            self.cameras.setdefault("wrist", self.wrist_camera)
        if len(self.start_position) != 7:
            raise ValueError(
                f"start_position must have 7 elements (J1..J6 + gripper), got {len(self.start_position)}"
            )
        if len(self.home_position) != 7:
            raise ValueError(
                f"home_position must have 7 elements (J1..J6 + gripper), got {len(self.home_position)}"
            )
        if self.feedback_max_age_s <= 0:
            raise ValueError(f"feedback_max_age_s must be positive, got {self.feedback_max_age_s}")
        if not self.position_compare_motor_name:
            raise ValueError("position_compare_motor_name must not be empty")
        if not math.isfinite(self.position_compare_interval_s) or self.position_compare_interval_s <= 0:
            raise ValueError(
                f"position_compare_interval_s must be positive, got {self.position_compare_interval_s}"
            )
        if self.position_compare_timeout_ms <= 0:
            raise ValueError(
                f"position_compare_timeout_ms must be positive, got {self.position_compare_timeout_ms}"
            )
        if not math.isfinite(self.gravity_compensation_scale) or self.gravity_compensation_scale < 0:
            raise ValueError(
                "gravity_compensation_scale must be finite and non-negative, "
                f"got {self.gravity_compensation_scale}"
            )
        for name, value in (
            ("control_rate_hz", self.control_rate_hz),
            ("feedback_rate_hz", self.feedback_rate_hz),
        ):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive when set, got {value}")
        if (
            not math.isfinite(self.joint_target_interpolation_time_s)
            or self.joint_target_interpolation_time_s < 0
        ):
            raise ValueError(
                "joint_target_interpolation_time_s must be non-negative, "
                f"got {self.joint_target_interpolation_time_s}"
            )


@RobotConfig.register_subclass("rebot_rs_follower")
@dataclass
class RebotRSFollowerRobotConfig(RobotConfig, RebotRSFollowerConfig):
    """Registered configuration for the reBot RS follower robot.

    This follower does not perform LeRobot motor calibration itself
    (``is_calibrated`` is always true); complete any required actuator
    calibration and SDK hardware setup before the first run. The inherited
    ``calibration_dir`` option is retained for the common robot-config
    interface and is not used by this implementation.
    """

    def __post_init__(self):
        RebotRSFollowerConfig.__post_init__(self)
        RobotConfig.__post_init__(self)
