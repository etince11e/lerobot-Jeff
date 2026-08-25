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

from contextlib import contextmanager
from threading import Event, Lock
from unittest.mock import MagicMock

import numpy as np
from motorbridge import CallError
from reBotArm_control_py.actuator import JointCfg, JointGroup, RebotArm


@contextmanager
def _assert_raises(error_type: type[Exception], message: str):
    try:
        yield
    except error_type as exc:
        assert message in str(exc)
    else:
        raise AssertionError(f"Expected {error_type.__name__}: {message}")


def _robstride_group(*motors: MagicMock) -> JointGroup:
    joint_cfgs = [
        JointCfg(
            name=f"joint{i}",
            motor_id=i,
            feedback_id=0xFD,
            model="rs-00",
            vendor="robstride",
        )
        for i in range(1, len(motors) + 1)
    ]
    return JointGroup(
        name="arm",
        joint_names=[cfg.name for cfg in joint_cfgs],
        all_joints=joint_cfgs,
        motor_map={cfg.name: motor for cfg, motor in zip(joint_cfgs, motors, strict=True)},
        ctrl_map={},
    )


def test_cached_position_read_performs_no_motor_io():
    motors = [MagicMock(), MagicMock()]
    motors[0].robstride_get_param_f32.return_value = 0.25
    motors[1].robstride_get_param_f32.return_value = -0.5
    group = _robstride_group(*motors)

    with _assert_raises(RuntimeError, "not initialized"):
        group.get_positions(request_feedback=False)

    assert np.allclose(group.get_positions(request_feedback=True), [0.25, -0.5])
    calls_after_refresh = [motor.robstride_get_param_f32.call_count for motor in motors]

    assert np.allclose(group.get_positions(request_feedback=False), [0.25, -0.5])
    assert [motor.robstride_get_param_f32.call_count for motor in motors] == calls_after_refresh


def test_mit_position_read_uses_type2_cache_without_mech_position_query():
    motors = [MagicMock(), MagicMock()]
    motors[0].get_state.return_value = {"pos": 0.25}
    motors[1].get_state.return_value = {"pos": -0.5}
    group = _robstride_group(*motors)
    group._mode = "mit"

    assert np.allclose(group.get_positions(request_feedback=False), [0.25, -0.5])
    for motor in motors:
        motor.robstride_get_param_f32.assert_not_called()
        motor.get_state.assert_called_once_with()


def test_mit_velocity_read_uses_type2_cache_without_feedback_request():
    motors = [MagicMock(), MagicMock()]
    motors[0].get_state.return_value = {"vel": 0.1}
    motors[1].get_state.return_value = {"vel": -0.2}
    group = _robstride_group(*motors)
    group._mode = "mit"

    assert np.allclose(group.get_velocities(request_feedback=False), [0.1, -0.2])
    for motor in motors:
        motor.request_feedback.assert_not_called()
        motor.get_state.assert_called_once_with()


def test_compare_cached_motor_state_to_mech_position():
    motor = MagicMock()
    motor.get_state.return_value = {"pos": 0.523}
    motor.robstride_get_param_f32.return_value = 0.521
    group = _robstride_group(motor)

    result = group.compare_cached_state_to_mech_position("joint1", timeout_ms=100)

    assert result["state"] == {"pos": 0.523}
    assert result["type2_pos"] == 0.523
    assert result["mech_pos"] == 0.521
    assert np.isclose(result["diff"], 0.002)
    motor.get_state.assert_called_once_with()
    motor.robstride_get_param_f32.assert_called_once_with(0x7019, 100)


def test_failed_sweep_keeps_previous_cache_and_timestamp():
    motors = [MagicMock(), MagicMock()]
    motors[0].robstride_get_param_f32.side_effect = [0.1, 0.3]
    motors[1].robstride_get_param_f32.side_effect = [0.2, CallError("feedback timeout")]
    group = _robstride_group(*motors)

    assert np.allclose(group.refresh_position_cache(), [0.1, 0.2])
    timestamp = group._position_cache_timestamp

    with _assert_raises(CallError, "feedback timeout"):
        group.refresh_position_cache()

    assert np.allclose(group.get_positions(request_feedback=False), [0.1, 0.2])
    assert group._position_cache_timestamp == timestamp
    assert isinstance(group.position_cache_error, CallError)


def test_nonfinite_feedback_does_not_replace_cache():
    motor = MagicMock()
    motor.robstride_get_param_f32.side_effect = [0.4, np.nan]
    group = _robstride_group(motor)

    assert np.allclose(group.refresh_position_cache(), [0.4])
    with _assert_raises(RuntimeError, "Non-finite"):
        group.refresh_position_cache()

    assert np.allclose(group.get_positions(request_feedback=False), [0.4])


def test_background_feedback_loop_refreshes_and_stops():
    refreshed = Event()

    class FakeGroup:
        name = "arm"
        has_position_cache = True

        def refresh_position_cache(self, timeout_ms: int) -> np.ndarray:
            assert timeout_ms == 10
            refreshed.set()
            return np.zeros(1, dtype=np.float64)

    arm = RebotArm.__new__(RebotArm)
    arm._groups = {"arm": FakeGroup()}
    arm._feedback_rate = 100.0
    arm._feedback_timeout_ms = 10
    arm._feedback_running = False
    arm._feedback_stop_event = Event()
    arm._feedback_thread = None
    arm._feedback_error_reported = set()
    arm._diagnostics_lock = Lock()
    arm._feedback_last_sweep_ms = None
    arm._feedback_sweep_count = 0
    arm._feedback_sweep_error_count = 0

    arm.start_feedback_loop()
    assert refreshed.wait(timeout=1.0)
    assert arm.feedback_loop_active

    arm.stop_feedback_loop()
    assert not arm.feedback_loop_active


def test_control_loop_can_skip_periodic_feedback_sweep():
    arm = RebotArm.__new__(RebotArm)
    arm._running = False
    arm._ctrl_thread = None
    arm._ctrl_fn = None
    arm._rate = 100.0
    arm._ctrl_rate = 100.0
    arm._feedback_running = False
    arm._feedback_stop_event = Event()
    arm._feedback_thread = None

    started = Event()
    release = Event()

    arm.start_feedback_loop = MagicMock()

    def control_loop_stub():
        started.set()
        release.wait(timeout=1.0)

    arm._control_loop_impl = control_loop_stub

    arm.start_control_loop(lambda *_: None, feedback_sweep=False)

    arm.start_feedback_loop.assert_not_called()
    assert started.wait(timeout=1.0)
    assert arm.control_loop_active
    release.set()
    arm.stop_control_loop()
