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

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lerobot.utils.robot_utils import rotation_6d_to_quaternion

PICO_NEUTRAL_POSE = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)


@dataclass
class PicoToRebotJointMap:
    """Linear mapping from Pico pose deltas to reBot joint targets."""

    pan_deg_per_m: float = 80.0
    lift_deg_per_m: float = 80.0
    elbow_deg_per_m: float = -80.0
    wrist_deg_per_rad: float = 35.0
    gripper_close_deg: float = 270.0


@dataclass
class RebotB601PicoTeleopSession:
    """Stateful bridge from Pico4 TCP actions to reBot B601 joint actions."""

    mapping: PicoToRebotJointMap = field(default_factory=PicoToRebotJointMap)
    joint_anchor: dict[str, float] | None = None
    pico_pos_anchor: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    pico_euler_anchor: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    last_action: dict[str, float] | None = None

    def sync(self, joint_positions: dict[str, float], pico_action: dict[str, float]) -> None:
        """Freeze the current robot pose as the new reference point."""
        self.joint_anchor = dict(joint_positions)
        self.pico_pos_anchor = self._pico_xyz(pico_action)
        self.pico_euler_anchor = self._pico_euler(pico_action)
        self.last_action = {f"{joint}.pos": value for joint, value in joint_positions.items()}

    def build_action(self, pico_action: dict[str, float]) -> dict[str, float]:
        """Map a Pico4 TCP action to a full reBot B601 joint action."""
        if self.joint_anchor is None:
            raise RuntimeError("Pico/reBot session is not anchored.")

        action = dict(self.joint_anchor)
        pos_delta = self._pico_xyz(pico_action) - self.pico_pos_anchor
        euler_delta = self._pico_euler(pico_action) - self.pico_euler_anchor

        action["shoulder_pan"] = (
            self.joint_anchor.get("shoulder_pan", 0.0) + pos_delta[1] * self.mapping.pan_deg_per_m
        )
        action["shoulder_lift"] = (
            self.joint_anchor.get("shoulder_lift", 0.0) + pos_delta[2] * self.mapping.lift_deg_per_m
        )
        action["elbow_flex"] = (
            self.joint_anchor.get("elbow_flex", 0.0) + pos_delta[0] * self.mapping.elbow_deg_per_m
        )
        action["wrist_roll"] = (
            self.joint_anchor.get("wrist_roll", 0.0) + euler_delta[0] * self.mapping.wrist_deg_per_rad
        )
        action["wrist_flex"] = (
            self.joint_anchor.get("wrist_flex", 0.0) + euler_delta[1] * self.mapping.wrist_deg_per_rad
        )
        action["wrist_yaw"] = (
            self.joint_anchor.get("wrist_yaw", 0.0) + euler_delta[2] * self.mapping.wrist_deg_per_rad
        )
        action["gripper"] = self.rebot_gripper_from_pico(
            float(pico_action["gripper.pos"]), self.mapping.gripper_close_deg
        )

        self.last_action = {f"{joint}.pos": value for joint, value in action.items()}
        return self.last_action

    def build_hold_action(self, pico_action: dict[str, float]) -> dict[str, float]:
        """Keep the current robot pose while updating the gripper from Pico trigger."""
        if self.last_action is None:
            return self.build_action(pico_action)

        action = dict(self.last_action)
        action["gripper.pos"] = self.rebot_gripper_from_pico(
            float(pico_action["gripper.pos"]), self.mapping.gripper_close_deg
        )
        self.last_action = action
        return action

    @staticmethod
    def pico_neutral_pose(gripper_deg: float) -> np.ndarray:
        pose = PICO_NEUTRAL_POSE.copy()
        pose[7] = float(np.clip(1.0 + gripper_deg / 270.0, 0.0, 1.0))
        return pose

    @staticmethod
    def extract_joint_positions(observation: dict[str, object]) -> dict[str, float]:
        return {
            key.removesuffix(".pos"): float(value)
            for key, value in observation.items()
            if key.endswith(".pos")
        }

    @staticmethod
    def pico_gripper_from_rebot(gripper_deg: float) -> float:
        return float(np.clip(1.0 + gripper_deg / 270.0, 0.0, 1.0))

    @staticmethod
    def rebot_gripper_from_pico(gripper_pos: float, close_deg: float) -> float:
        return -float(np.clip(1.0 - gripper_pos, 0.0, 1.0) * close_deg)

    @staticmethod
    def _pico_xyz(action: dict[str, float]) -> np.ndarray:
        return np.array([action["tcp.x"], action["tcp.y"], action["tcp.z"]], dtype=np.float32)

    @staticmethod
    def _pico_euler(action: dict[str, float]) -> np.ndarray:
        r6d = np.array([action[f"tcp.r{i}"] for i in range(1, 7)], dtype=np.float32)
        qw, qx, qy, qz = rotation_6d_to_quaternion(r6d)

        roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
        pitch = math.asin(float(np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0)))
        yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
        return np.array([roll, pitch, yaw], dtype=np.float32)
