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

"""Pico4 teleoperation example for the reBot B601 follower.

The reBot B601 driver in this tree is joint-space only. Pico4 emits a shared
TCP pose schema used by Cartesian robots such as Flexiv. This example bridges
the two conservatively by mapping Pico pose deltas to small joint-space targets.
It is intended as a practical teleop starting point, not a geometric IK solver.
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from dataclasses import dataclass

import numpy as np

from lerobot.robots.rebot_b601_follower import RebotB601Follower, RebotB601FollowerRobotConfig
from lerobot.teleoperators.pico4 import Pico4, Pico4Config
from lerobot.utils.robot_utils import precise_sleep, rotation_6d_to_quaternion
from lerobot.utils.utils import init_logging

logger = logging.getLogger(__name__)

PICO_NEUTRAL_POSE = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)


@dataclass
class PicoToRebotJointMap:
    """Linear joint-space mapping from Pico target deltas to B601 joint targets."""

    pan_deg_per_m: float = 80.0
    lift_deg_per_m: float = 80.0
    elbow_deg_per_m: float = -80.0
    wrist_deg_per_rad: float = 35.0
    gripper_close_deg: float = 270.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Damiao serial port or SocketCAN channel.")
    parser.add_argument("--can-adapter", choices=["damiao", "socketcan"], default="damiao")
    parser.add_argument("--id", default="rebot_b601_pico4")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration-s", type=float, default=None)
    parser.add_argument(
        "--max-relative-target",
        type=float,
        default=2.0,
        help="Per-frame relative joint target cap in degrees, enforced by the robot driver.",
    )
    parser.add_argument("--pos-sensitivity", type=float, default=0.8)
    parser.add_argument("--ori-sensitivity", type=float, default=0.5)
    parser.add_argument("--max-pos-velocity", type=float, default=0.25)
    parser.add_argument("--max-rot-velocity", type=float, default=1.2)
    parser.add_argument("--pan-deg-per-m", type=float, default=PicoToRebotJointMap.pan_deg_per_m)
    parser.add_argument("--lift-deg-per-m", type=float, default=PicoToRebotJointMap.lift_deg_per_m)
    parser.add_argument("--elbow-deg-per-m", type=float, default=PicoToRebotJointMap.elbow_deg_per_m)
    parser.add_argument("--wrist-deg-per-rad", type=float, default=PicoToRebotJointMap.wrist_deg_per_rad)
    parser.add_argument("--gripper-close-deg", type=float, default=PicoToRebotJointMap.gripper_close_deg)
    return parser.parse_args()


def _read_joint_positions(robot: RebotB601Follower) -> dict[str, float]:
    obs = robot.get_observation()
    return {key.removesuffix(".pos"): float(value) for key, value in obs.items() if key.endswith(".pos")}


def _pico_gripper_from_rebot(gripper_deg: float) -> float:
    # Pico convention: 1=open, 0=closed. reBot default: 0=open, -270=closed.
    return float(np.clip(1.0 + gripper_deg / 270.0, 0.0, 1.0))


def _rebot_gripper_from_pico(gripper_pos: float, close_deg: float) -> float:
    return -float(np.clip(1.0 - gripper_pos, 0.0, 1.0) * close_deg)


def _r6d_to_euler(action: dict[str, float]) -> np.ndarray:
    r6d = np.array([action[f"tcp.r{i}"] for i in range(1, 7)], dtype=np.float32)
    qw, qx, qy, qz = rotation_6d_to_quaternion(r6d)

    roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    pitch = math.asin(float(np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0)))
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return np.array([roll, pitch, yaw], dtype=np.float32)


def _pico_xyz(action: dict[str, float]) -> np.ndarray:
    return np.array([action["tcp.x"], action["tcp.y"], action["tcp.z"]], dtype=np.float32)


def _build_rebot_action(
    pico_action: dict[str, float],
    joint_anchor: dict[str, float],
    pico_pos_anchor: np.ndarray,
    pico_euler_anchor: np.ndarray,
    mapping: PicoToRebotJointMap,
) -> dict[str, float]:
    pos_delta = _pico_xyz(pico_action) - pico_pos_anchor
    euler_delta = _r6d_to_euler(pico_action) - pico_euler_anchor

    action = dict(joint_anchor)
    action["shoulder_pan"] = joint_anchor.get("shoulder_pan", 0.0) + pos_delta[1] * mapping.pan_deg_per_m
    action["shoulder_lift"] = joint_anchor.get("shoulder_lift", 0.0) + pos_delta[2] * mapping.lift_deg_per_m
    action["elbow_flex"] = joint_anchor.get("elbow_flex", 0.0) + pos_delta[0] * mapping.elbow_deg_per_m
    action["wrist_roll"] = joint_anchor.get("wrist_roll", 0.0) + euler_delta[0] * mapping.wrist_deg_per_rad
    action["wrist_flex"] = joint_anchor.get("wrist_flex", 0.0) + euler_delta[1] * mapping.wrist_deg_per_rad
    action["wrist_yaw"] = joint_anchor.get("wrist_yaw", 0.0) + euler_delta[2] * mapping.wrist_deg_per_rad
    action["gripper"] = _rebot_gripper_from_pico(
        float(pico_action["gripper.pos"]), mapping.gripper_close_deg
    )

    return {f"{joint}.pos": value for joint, value in action.items()}


def main() -> None:
    args = _parse_args()
    init_logging()

    mapping = PicoToRebotJointMap(
        pan_deg_per_m=args.pan_deg_per_m,
        lift_deg_per_m=args.lift_deg_per_m,
        elbow_deg_per_m=args.elbow_deg_per_m,
        wrist_deg_per_rad=args.wrist_deg_per_rad,
        gripper_close_deg=args.gripper_close_deg,
    )

    robot = RebotB601Follower(
        RebotB601FollowerRobotConfig(
            id=args.id,
            port=args.port,
            can_adapter=args.can_adapter,
            max_relative_target=args.max_relative_target,
        )
    )
    teleop = Pico4(
        Pico4Config(
            id="pico4_rebot_b601",
            use_right_controller=True,
            use_left_controller=False,
            pos_sensitivity=args.pos_sensitivity,
            ori_sensitivity=args.ori_sensitivity,
            max_pos_velocity=args.max_pos_velocity,
            max_rot_velocity=args.max_rot_velocity,
            gripper_width=1.0,
        )
    )

    period_s = 1.0 / args.fps
    start_time = time.perf_counter()
    was_enabled = False
    joint_anchor: dict[str, float] | None = None
    pico_pos_anchor = np.zeros(3, dtype=np.float32)
    pico_euler_anchor = np.zeros(3, dtype=np.float32)
    last_action: dict[str, float] | None = None

    try:
        robot.connect()
        joints = _read_joint_positions(robot)
        PICO_NEUTRAL_POSE[7] = _pico_gripper_from_rebot(joints.get("gripper", 0.0))
        teleop.connect(current_tcp_pose_quat=PICO_NEUTRAL_POSE)
        joint_anchor = joints
        last_action = {f"{joint}.pos": value for joint, value in joints.items()}
        logger.info("Pico4 + reBot B601 teleop started. Hold grip to move; A resyncs anchors.")

        while True:
            loop_start = time.perf_counter()
            pico_action = teleop.get_action()
            enabled = bool(getattr(teleop, "_enabled", False))

            if teleop.get_reset_button():
                joint_anchor = _read_joint_positions(robot)
                pico_pos_anchor = _pico_xyz(pico_action)
                pico_euler_anchor = _r6d_to_euler(pico_action)
                last_action = {f"{joint}.pos": value for joint, value in joint_anchor.items()}
                logger.info("Anchors resynced to current robot and Pico poses.")

            if enabled and not was_enabled:
                joint_anchor = _read_joint_positions(robot)
                pico_pos_anchor = _pico_xyz(pico_action)
                pico_euler_anchor = _r6d_to_euler(pico_action)
                logger.info("Grip engaged; joint anchor captured.")

            if enabled and joint_anchor is not None:
                action = _build_rebot_action(
                    pico_action, joint_anchor, pico_pos_anchor, pico_euler_anchor, mapping
                )
                last_action = robot.send_action(action)
            elif last_action is not None:
                # Keep arm still, but allow trigger-only gripper updates while grip is released.
                hold_action = dict(last_action)
                hold_action["gripper.pos"] = _rebot_gripper_from_pico(
                    float(pico_action["gripper.pos"]), mapping.gripper_close_deg
                )
                last_action = robot.send_action(hold_action)

            was_enabled = enabled
            if args.duration_s is not None and time.perf_counter() - start_time >= args.duration_s:
                break
            precise_sleep(period_s - (time.perf_counter() - loop_start))
    except KeyboardInterrupt:
        pass
    finally:
        if teleop.is_connected:
            teleop.disconnect()
        if robot.is_connected:
            robot.disconnect()


if __name__ == "__main__":
    main()
