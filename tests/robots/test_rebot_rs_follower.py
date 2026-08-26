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

import time
from threading import Event, Lock
from unittest.mock import MagicMock, patch

import numpy as np

from lerobot.robots.rebot_rs_follower import RebotRSFollower, RebotRSFollowerRobotConfig


def test_camera_aliases_land_in_observation_features():
    robot = RebotRSFollower(RebotRSFollowerRobotConfig())

    assert robot.config.arm_control_mode == "mit"
    assert "head" in robot.config.cameras
    assert "wrist" in robot.config.cameras
    assert str(robot.config.head_camera.index_or_path) == "/dev/video4"
    assert str(robot.config.wrist_camera.index_or_path) == "/dev/video2"
    assert robot.config.head_camera.fourcc == "MJPG"
    assert robot.config.wrist_camera.fourcc == "MJPG"
    assert robot.config.start_position == [0.0163, 0.6469, 0.5653, -0.5734, 0.0225, 0.0290, 4.7]
    assert robot.config.home_position == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert robot.observation_features["head"] == (480, 640, 3)
    assert robot.observation_features["wrist"] == (480, 640, 3)


def test_start_pose_and_safe_home_use_distinct_targets():
    robot = RebotRSFollower(RebotRSFollowerRobotConfig())
    robot._connected = True
    robot._arm = MagicMock()
    robot._arm_group = MagicMock(num_joints=6)
    robot._q_target = np.ones(6, dtype=np.float64)
    robot._q_seed = np.ones(6, dtype=np.float64)
    robot._has_gripper = True
    robot._gripper_target = 0.2
    robot.cameras = {}

    readings = iter(
        [
            np.full(6, 0.4, dtype=np.float64),
            np.array(robot.config.start_position[:6], dtype=np.float64),
            np.full(6, 0.2, dtype=np.float64),
            np.array(robot.config.home_position[:6], dtype=np.float64),
        ]
    )
    robot._read_arm_positions = MagicMock(
        side_effect=lambda *_, **__: next(readings, np.zeros(6, dtype=np.float64))
    )

    with patch("lerobot.robots.rebot_rs_follower.rebot_rs_follower.time.sleep", lambda *_: None):
        robot.reset_to_initial_position()
        robot.safe_home(max_vel=10.0, send_freq=10.0, timeout=1.0)

    assert np.allclose(robot._q_target, robot.config.home_position[:6])
    assert np.allclose(robot._q_seed, robot.config.home_position[:6])
    assert robot._gripper_target == robot.config.home_position[6]


def test_move_to_joint_target_reports_timeout_as_failure():
    robot = RebotRSFollower(RebotRSFollowerRobotConfig(head_camera=None, wrist_camera=None))
    robot._connected = True
    robot._arm = MagicMock(control_loop_active=True)
    robot._arm_group = MagicMock(num_joints=6)
    robot._has_gripper = True
    robot._read_arm_positions = MagicMock(return_value=np.zeros(6, dtype=np.float64))

    with patch("lerobot.robots.rebot_rs_follower.rebot_rs_follower.time.monotonic", side_effect=[0.0, 2.0]):
        reached = robot.go_to_start_position(timeout=1.0, max_vel=0.01, send_freq=10.0)

    assert reached is False


def test_get_observation_uses_camera_latest_buffer_without_reading_camera():
    robot = RebotRSFollower(RebotRSFollowerRobotConfig())
    robot._connected = True
    robot._arm = MagicMock()
    robot._sdk = MagicMock()
    robot._model = MagicMock()
    robot._arm_group = MagicMock(num_joints=6)
    robot._sdk.pad_q_for_model.side_effect = lambda _model, q, _n: np.asarray(q)
    robot._sdk.compute_fk.return_value = (np.array([0.3, 0.2, 0.1], dtype=np.float64), None, None)
    robot._read_arm_positions = MagicMock(
        return_value=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float64)
    )
    robot._read_gripper_position = MagicMock(return_value=0.75)

    head_camera = MagicMock()
    head_camera.frame_lock = Lock()
    head_camera.latest_frame = np.zeros((2, 2, 3), dtype=np.uint8)
    head_camera.latest_timestamp = time.perf_counter()
    head_camera.is_connected = True
    head_camera.read_latest = MagicMock()
    robot.cameras = {"head": head_camera}

    robot.config.cameras = {"head": robot.config.head_camera}

    obs = robot.get_observation()

    assert np.allclose([obs["joint1.pos"], obs["joint6.pos"]], [0.1, 0.6])
    assert obs["gripper.pos"] == 0.75
    assert np.allclose([obs["tcp.x"], obs["tcp.y"], obs["tcp.z"]], [0.3, 0.2, 0.1])
    assert obs["head"].shape == (2, 2, 3)
    head_camera.read_latest.assert_not_called()


def test_cached_joint_reads_do_not_request_hardware_feedback():
    robot = RebotRSFollower(RebotRSFollowerRobotConfig())
    robot._arm_group = MagicMock(num_joints=6)
    robot._arm_group.get_positions.return_value = np.arange(6, dtype=np.float64)
    robot._arm_group.position_cache_age_s = 0.01
    robot._arm_group.position_cache_error = None

    positions = robot._read_arm_positions(request_feedback=False)

    assert np.allclose(positions, np.arange(6, dtype=np.float64))
    robot._arm_group.get_positions.assert_called_once_with(request_feedback=False)


def test_latest_target_is_interpolated_without_queuing_old_targets():
    config = RebotRSFollowerRobotConfig(
        head_camera=None,
        wrist_camera=None,
        joint_target_interpolation_time_s=0.02,
    )
    robot = RebotRSFollower(config)

    with robot._target_lock:
        robot._q_target = np.ones(6, dtype=np.float64)

    q0 = robot._interpolated_command(now=10.00)
    q1 = robot._interpolated_command(now=10.01)
    q2 = robot._interpolated_command(now=10.02)
    assert np.allclose(q0, 0.0)
    assert np.all(q1 > q0)
    assert np.all(q2 > q1)

    # A new target starts from the command currently being sent. It does not
    # wait for a queued trajectory made from obsolete targets.
    with robot._target_lock:
        robot._q_target = np.full(6, 2.0, dtype=np.float64)
    q3 = robot._interpolated_command(now=10.025)
    assert np.all(q3 > q2)


def test_async_ik_publishes_completed_result_before_newest_request():
    config = RebotRSFollowerRobotConfig(head_camera=None, wrist_camera=None)
    robot = RebotRSFollower(config)
    robot._connected = True
    robot.cameras = {}
    robot._arm_group = MagicMock(num_joints=6)
    robot._sdk = MagicMock()
    robot._sdk.IKParams.return_value = object()
    robot._model = object()
    robot._data = object()
    robot._end_frame_id = 0

    first_started = Event()
    release_first = Event()
    second_started = Event()
    release_second = Event()

    def solve_ik(_model, _data, _frame_id, target, _seed, _params, controlled_joints):
        if target == "first":
            first_started.set()
            assert release_first.wait(timeout=2.0)
            q_value = 1.0
        else:
            second_started.set()
            assert release_second.wait(timeout=2.0)
            q_value = 2.0
        return MagicMock(success=True, q=np.full(controlled_joints, q_value), error=0.0)

    robot._sdk.solve_ik.side_effect = solve_ik
    robot._start_ik_worker()
    try:
        with robot._ik_condition:
            robot._ik_request_seq += 1
            robot._ik_request = (robot._ik_request_seq, robot._ik_epoch, "first")
            robot._ik_condition.notify()
        assert first_started.wait(timeout=2.0)

        with robot._ik_condition:
            robot._ik_request_seq += 1
            robot._ik_request = (robot._ik_request_seq, robot._ik_epoch, "second")
            robot._ik_condition.notify()
        release_first.set()

        assert second_started.wait(timeout=2.0)
        # A newer request does not invalidate the completed result within the
        # same teleoperation epoch. The latest-only mailbox still prevents a
        # queue of old requests from accumulating.
        assert np.allclose(robot._q_target, 1.0)

        release_second.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not np.allclose(robot._q_target, 2.0):
            time.sleep(0.005)
        assert np.allclose(robot._q_target, 2.0)
        assert robot._ik_dropped_results == 0
        assert robot._ik_dropped_epoch_results == 0
    finally:
        robot._stop_ik_worker()


def test_send_action_only_submits_ik_request():
    config = RebotRSFollowerRobotConfig(head_camera=None, wrist_camera=None)
    robot = RebotRSFollower(config)
    robot._connected = True
    robot._arm = MagicMock()
    robot.cameras = {}
    robot._sdk = MagicMock()
    robot._sdk.pos_rot_to_se3.return_value = "target"

    action = dict.fromkeys(robot.action_features, 0.0)
    action["tcp.r1"] = 1.0
    action["tcp.r5"] = 1.0

    returned = robot.send_action(action)

    assert returned == action
    robot._sdk.solve_ik.assert_not_called()
    with robot._ik_condition:
        assert robot._ik_request is not None


def test_mit_control_sends_gravity_feedforward_torque():
    config = RebotRSFollowerRobotConfig(head_camera=None, wrist_camera=None)
    robot = RebotRSFollower(config)
    robot._arm_group = MagicMock(num_joints=6)
    robot._arm_group.get_positions.return_value = np.zeros(6, dtype=np.float64)
    robot._sdk = MagicMock()
    robot._sdk.pad_q_for_model.side_effect = lambda _model, q, _n: np.asarray(q)
    robot._sdk.compute_generalized_gravity.return_value = np.arange(6, dtype=np.float64)
    robot._model = object()
    robot._dynamics_data = object()
    robot._connected = True

    robot._loop_cb(None, 0.005)

    robot._arm_group.send_mit.assert_called_once()
    sent_tau = robot._arm_group.send_mit.call_args.kwargs["tau"]
    assert np.allclose(sent_tau, np.arange(6, dtype=np.float64))


def test_async_ik_result_is_dropped_after_epoch_invalidation():
    config = RebotRSFollowerRobotConfig(head_camera=None, wrist_camera=None)
    robot = RebotRSFollower(config)
    robot._connected = True
    robot.cameras = {}
    robot._arm_group = MagicMock(num_joints=6)
    robot._sdk = MagicMock()
    robot._sdk.IKParams.return_value = object()
    robot._model = object()
    robot._data = object()
    robot._end_frame_id = 0

    started = Event()
    release = Event()

    def solve_ik(*_args, controlled_joints):
        started.set()
        assert release.wait(timeout=2.0)
        return MagicMock(success=True, q=np.ones(controlled_joints), error=0.0)

    robot._sdk.solve_ik.side_effect = solve_ik
    robot._start_ik_worker()
    try:
        with robot._ik_condition:
            robot._ik_request_seq += 1
            robot._ik_request = (robot._ik_request_seq, robot._ik_epoch, "target")
            robot._ik_condition.notify()
        assert started.wait(timeout=2.0)

        robot._invalidate_ik_requests()
        release.set()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and robot._ik_dropped_epoch_results == 0:
            time.sleep(0.005)
        assert robot._ik_dropped_results == 1
        assert robot._ik_dropped_epoch_results == 1
        assert np.allclose(robot._q_target, 0.0)
    finally:
        robot._stop_ik_worker()
