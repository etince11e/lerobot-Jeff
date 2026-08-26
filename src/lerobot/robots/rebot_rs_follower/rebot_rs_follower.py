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

import importlib
import logging
import sys
import threading
import time
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from lerobot.cameras import make_cameras_from_configs
from lerobot.lerobot_types import RobotAction, RobotObservation
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected
from lerobot.utils.robot_utils import matrix_to_pose7d

from ..robot import Robot
from .config_rebot_rs_follower import RebotRSFollowerRobotConfig

logger = logging.getLogger(__name__)

TCP_ACTION_KEYS = (
    "tcp.x",
    "tcp.y",
    "tcp.z",
    "tcp.r1",
    "tcp.r2",
    "tcp.r3",
    "tcp.r4",
    "tcp.r5",
    "tcp.r6",
    "gripper.pos",
)

# The dataset stores robot state in the same Cartesian representation and
# ordering as the action. Camera observations remain separate image features.
TCP_OBSERVATION_KEYS = TCP_ACTION_KEYS


def _try_import_rebotarm_sdk():
    return SimpleNamespace(
        RebotArm=importlib.import_module("reBotArm_control_py.actuator").RebotArm,
        compute_fk=importlib.import_module("reBotArm_control_py.kinematics").compute_fk,
        get_end_effector_frame_id=importlib.import_module(
            "reBotArm_control_py.kinematics"
        ).get_end_effector_frame_id,
        load_robot_model=importlib.import_module("reBotArm_control_py.kinematics").load_robot_model,
        pad_q_for_model=importlib.import_module("reBotArm_control_py.kinematics").pad_q_for_model,
        solve_ik=importlib.import_module("reBotArm_control_py.kinematics").solve_ik,
        pos_rot_to_se3=importlib.import_module("reBotArm_control_py.kinematics").pos_rot_to_se3,
        IKParams=importlib.import_module("reBotArm_control_py.kinematics.inverse_kinematics").IKParams,
        compute_generalized_gravity=importlib.import_module(
            "reBotArm_control_py.dynamics"
        ).compute_generalized_gravity,
    )


def _candidate_sdk_paths(configured_path: Path | None) -> list[Path]:
    paths = []
    if configured_path is not None:
        paths.append(Path(configured_path).expanduser())

    this_file = Path(__file__).resolve()
    paths.extend(
        [
            this_file.parents[4] / "third_party" / "reBotArm_control_py",
            Path.cwd() / "third_party" / "reBotArm_control_py",
        ]
    )
    return paths


def _load_rebotarm_sdk(configured_path: Path | None):
    try:
        return _try_import_rebotarm_sdk()
    except ImportError as first_error:
        for path in _candidate_sdk_paths(configured_path):
            if not path.exists():
                continue
            import_root = (
                path.parent
                if path.name == "reBotArm_control_py" and (path / "__init__.py").exists()
                else path
            )
            path_str = str(import_root)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
            try:
                return _try_import_rebotarm_sdk()
            except ImportError:
                continue
        raise ImportError(
            "reBotArm_control_py is required for rebot_rs_follower. Install it into the current "
            "environment or pass --robot.sdk_path=/path/to/lerobot/third_party/reBotArm_control_py."
        ) from first_error


def _rotation_6d_to_matrix(r6d: np.ndarray) -> np.ndarray:
    r6d = np.asarray(r6d, dtype=np.float64).reshape(6)
    a1 = r6d[:3]
    a2 = r6d[3:]
    n1 = np.linalg.norm(a1)
    if n1 < 1e-9:
        return np.eye(3)
    b1 = a1 / n1
    b2 = a2 - np.dot(b1, a2) * b1
    n2 = np.linalg.norm(b2)
    if n2 < 1e-9:
        return np.eye(3)
    b2 = b2 / n2
    b3 = np.cross(b1, b2)
    return np.column_stack((b1, b2, b3))


class RebotRSFollower(Robot):
    """reBot RS follower arm using reBotArm_control_py IK and RobStride control."""

    config_class = RebotRSFollowerRobotConfig
    name = "rebot_rs_follower"

    def __init__(self, config: RebotRSFollowerRobotConfig):
        super().__init__(config)
        self.config = config
        self.cameras = make_cameras_from_configs(config.cameras)
        self._sdk = None
        self._arm = None
        self._arm_group = None
        self._gripper_group = None
        self._has_gripper = False
        self._model = None
        self._data = None
        self._dynamics_data = None
        self._end_frame_id: int | None = None
        self._arm_joint_names = [f"joint{i}" for i in range(1, 7)]
        # ``_q_target`` is the newest successfully solved IK goal (updated by
        # the IK worker). ``_q_command`` is the high-rate command actually sent
        # to RobStride. Keeping them separate removes the 30 Hz staircase while
        # still ensuring that a newer goal supersedes an older one.
        self._q_target = np.zeros(6, dtype=np.float64)
        self._q_command = np.zeros(6, dtype=np.float64)
        self._q_velocity = np.zeros(6, dtype=np.float64)
        self._last_interp_time: float | None = None
        self._target_lock = threading.Lock()
        self._q_seed = np.zeros(6, dtype=np.float64)
        # Cartesian teleoperation requests are latest-only.  The application
        # thread publishes a request and returns immediately; a single worker
        # owns Pinocchio ``Data`` and performs IK without blocking the control
        # loop.  A condition (rather than an unbounded Queue) deliberately
        # prevents old hand poses from accumulating when IK is slower than the
        # teleoperation rate.
        self._ik_condition = threading.Condition()
        self._ik_request: tuple[int, int, object] | None = None
        self._ik_request_times: dict[int, float] = {}
        self._ik_request_seq = 0
        self._ik_epoch = 0
        self._ik_stop_requested = False
        self._ik_thread: threading.Thread | None = None
        self._ik_worker_seed = np.zeros(6, dtype=np.float64)
        self._gripper_target = config.gripper_open_pos
        self._connected = False
        self._last_ik_success = True
        self._last_ik_duration_s: float | None = None
        self._ik_dropped_results = 0
        self._ik_dropped_epoch_results = 0
        self._latency_lock = threading.Lock()
        self._ik_last_queue_ms: float | None = None
        self._ik_last_iterations: int | None = None
        self._ik_last_seq: int | None = None
        self._ik_last_latest_seq: int | None = None
        self._ik_published_results = 0
        self._control_callback_ms: float | None = None
        self._last_command_actual_error_rad: float | None = None
        self._camera_max_age_ms = 500
        self._stale_camera_warnings: set[str] = set()
        self._stale_feedback_warnings: set[str] = set()
        self._gravity_warning_logged = False
        self._position_compare_stop_event = threading.Event()
        self._position_compare_thread: threading.Thread | None = None

    @property
    def _arm_mode(self) -> str:
        return "posvel" if self.config.arm_control_mode == "pos_vel" else self.config.arm_control_mode

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        features: dict[str, type | tuple] = dict.fromkeys(TCP_OBSERVATION_KEYS, float)
        for cam_name, cfg in self.config.cameras.items():
            if getattr(cfg, "use_rgb", True):
                features[cam_name] = (cfg.height, cfg.width, 3)
            if getattr(cfg, "use_depth", False):
                features[f"{cam_name}_depth"] = (cfg.height, cfg.width, 1)
        return features

    @cached_property
    def action_features(self) -> dict[str, type]:
        return dict.fromkeys(TCP_ACTION_KEYS, float)

    @property
    def is_connected(self) -> bool:
        return (
            self._connected
            and self._arm is not None
            and all(cam.is_connected for cam in self.cameras.values())
        )

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        if self._arm_mode not in ("mit", "posvel"):
            raise ValueError("arm_control_mode must be 'mit', 'posvel', or 'pos_vel'")

        self._sdk = _load_rebotarm_sdk(self.config.sdk_path)
        self._arm = self._sdk.RebotArm(hw_yaml=self.config.hw_yaml)
        self._arm_group = self._arm.groups.get("arm")
        self._gripper_group = self._arm.groups.get("gripper")
        if self._arm_group is None:
            raise ValueError("reBotArm_control_py hardware config must define an 'arm' group.")
        if (
            self.config.position_compare_enabled
            and self.config.position_compare_motor_name not in self._arm_group.joint_names
        ):
            raise ValueError(
                "position_compare_motor_name must name a joint in the arm group; "
                f"got {self.config.position_compare_motor_name!r}, "
                f"available={self._arm_group.joint_names}"
            )

        if self.config.hw_yaml is not None:
            logger.warning(
                "rebot_rs_follower currently uses the SDK default kinematics config for IK; "
                "hw_yaml is passed to the actuator layer only."
            )
        self._model = self._sdk.load_robot_model()
        self._end_frame_id = self._sdk.get_end_effector_frame_id(self._model)
        self._data = self._model.createData()
        # IK and gravity computation run in different threads. Pinocchio Data
        # is mutable, so the control loop must use its own Data instance.
        self._dynamics_data = self._model.createData()
        self._gravity_warning_logged = False

        self._arm.connect()
        if self._arm_mode == "mit":
            self._arm_group.mode_mit()
        else:
            self._arm_group.mode_pos_vel()
        self._arm_group.enable()

        self._has_gripper = bool(self._arm.has_gripper)
        if self._has_gripper:
            self._gripper_group.mode_mit()
            self._gripper_group.enable()

        # Prime the exact hardware cache before the background feedback worker
        # starts. Normal observations use the cache and perform no CAN I/O.
        q_now = self._read_arm_positions(request_feedback=True)
        with self._target_lock:
            self._q_target = q_now.copy()
            self._q_command = q_now.copy()
            self._q_velocity.fill(0.0)
            self._last_interp_time = None
        with self._target_lock:
            self._q_seed = q_now.copy()
            self._ik_worker_seed = q_now.copy()
        if self._has_gripper:
            gripper_pos = self._gripper_group.get_positions()[0]
            self._gripper_target = float(gripper_pos)

        # MIT Type-2 responses update MotorBridge's per-motor RX cache. Do not
        # start the periodic 0x7019 feedback sweep in that mode: it competes
        # with the control frames and creates a low-frequency position step.
        # POS_VEL keeps the legacy sweep until its response semantics are
        # verified separately.
        self._arm.start_control_loop(
            self._loop_cb,
            rate=self.config.control_rate_hz,
            feedback_sweep=self._arm_mode != "mit",
        )
        for camera in self.cameras.values():
            camera.connect()
        self._connected = True
        self._start_ik_worker()
        self._start_position_compare_diagnostic()
        logger.info("%s connected with %s.", self, self.config.hw_yaml or "SDK default hardware YAML")

    def _start_position_compare_diagnostic(self) -> None:
        """Start the opt-in low-rate Type-2 versus mechPos diagnostic."""

        if not self.config.position_compare_enabled or self._arm_group is None:
            return
        self._position_compare_stop_event.clear()
        self._position_compare_thread = threading.Thread(
            target=self._position_compare_loop,
            name="rebot-rs-position-compare",
            daemon=True,
        )
        self._position_compare_thread.start()

    def _position_compare_loop(self) -> None:
        interval = self.config.position_compare_interval_s
        motor_name = self.config.position_compare_motor_name
        while not self._position_compare_stop_event.wait(interval):
            group = self._arm_group
            if group is None:
                return
            try:
                result = group.compare_cached_state_to_mech_position(
                    motor_name,
                    timeout_ms=self.config.position_compare_timeout_ms,
                )
                if result.get("error") is not None:
                    logger.warning("[POS_COMPARE] %s: %s", motor_name, result["error"])
                elif result["type2_pos"] is None:
                    logger.warning("[POS_COMPARE] %s: no cached MotorBridge state", motor_name)
                else:
                    logger.info(
                        "[POS_COMPARE] %s state=%r type2=%+.6f rad mechPos=%+.6f rad "
                        "diff=%+.6f rad query=%.1f ms",
                        motor_name,
                        result["state"],
                        result["type2_pos"],
                        result["mech_pos"],
                        result["diff"],
                        result.get("query_ms", float("nan")),
                    )
            except Exception:
                logger.exception("[POS_COMPARE] %s comparison failed", motor_name)

    def _stop_position_compare_diagnostic(self) -> None:
        self._position_compare_stop_event.set()
        thread = self._position_compare_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._position_compare_thread = None

    def configure(self) -> None:
        if not self.is_connected:
            return
        if self._arm_mode == "mit":
            self._arm_group.mode_mit()
        else:
            self._arm_group.mode_pos_vel()

    def _read_arm_positions(self, request_feedback: bool = False) -> np.ndarray:
        if self._arm_group is None:
            with self._target_lock:
                return self._q_command.copy()
        q = self._arm_group.get_positions(request_feedback=request_feedback)
        if not request_feedback:
            self._warn_if_feedback_stale("arm", self._arm_group)
        return np.asarray(q[: self._arm_group.num_joints], dtype=np.float64)

    def _read_gripper_position(self, request_feedback: bool = False) -> float:
        if not self._has_gripper or self._gripper_group is None:
            return self._gripper_target
        positions = self._gripper_group.get_positions(request_feedback=request_feedback)
        if not request_feedback:
            self._warn_if_feedback_stale("gripper", self._gripper_group)
        return float(positions[0]) if len(positions) else self._gripper_target

    def _warn_if_feedback_stale(self, group_name: str, group) -> None:
        age_s = getattr(group, "position_cache_age_s", None)
        error = getattr(group, "position_cache_error", None)
        if not isinstance(age_s, (int, float)):
            age_s = None
        if age_s is None or age_s > self.config.feedback_max_age_s:
            if group_name not in self._stale_feedback_warnings:
                detail = f" Last refresh error: {error}" if error is not None else ""
                logger.warning(
                    "reBot RS %s position feedback cache is stale (age=%s, max=%.3f s).%s",
                    group_name,
                    "unknown" if age_s is None else f"{age_s:.3f} s",
                    self.config.feedback_max_age_s,
                    detail,
                )
                self._stale_feedback_warnings.add(group_name)
        else:
            if group_name in self._stale_feedback_warnings:
                logger.info("reBot RS %s position feedback cache recovered.", group_name)
            self._stale_feedback_warnings.discard(group_name)

    def _interpolated_command(self, now: float | None = None) -> np.ndarray:
        """Return a latest-target command with continuous command velocity.

        A restarted linear segment makes the velocity jump whenever a new
        60-Hz teleoperation target arrives. Instead, the desired velocity is
        filtered and integrated at the RobStride control-loop rate. The target
        is still replaced immediately, so old targets are never queued.
        """

        now = time.monotonic() if now is None else now
        with self._target_lock:
            target = self._q_target.copy()
            duration = float(self.config.joint_target_interpolation_time_s)
            if duration <= 0.0:
                self._q_command = target
                self._q_velocity.fill(0.0)
                self._last_interp_time = now
                return self._q_command.copy()

            if self._last_interp_time is None:
                self._last_interp_time = now
                return self._q_command.copy()

            # Do not turn a delayed callback into a large position jump.
            dt = min(max(now - self._last_interp_time, 0.0), duration)
            self._last_interp_time = now
            if dt <= 0.0:
                return self._q_command.copy()

            alpha = 1.0 - np.exp(-dt / max(duration, 1e-3))
            desired_velocity = (target - self._q_command) / max(duration, 1e-3)
            self._q_velocity += alpha * (desired_velocity - self._q_velocity)
            q_next = self._q_command + self._q_velocity * dt

            # Stop exactly at a target instead of crossing it due to retained
            # velocity when the operator reverses direction.
            crossed = (target - self._q_command) * (target - q_next) < 0.0
            q_next = np.where(crossed, target, q_next)
            self._q_velocity = np.where(crossed, 0.0, self._q_velocity)
            self._q_command = q_next
            return self._q_command.copy()

    def _loop_cb(self, _, dt: float) -> None:
        if self._arm_group is None:
            return
        callback_started = time.perf_counter()
        q_command = self._interpolated_command()
        if self._arm_mode == "mit":
            tau = None
            if self.config.gravity_compensation_enabled and self._dynamics_data is not None:
                try:
                    q_actual = self._arm_group.get_positions(request_feedback=False)
                    q_full = self._sdk.pad_q_for_model(self._model, q_actual, len(q_actual))
                    tau = self._sdk.compute_generalized_gravity(
                        self._model,
                        q_full,
                        self._dynamics_data,
                    )[: self._arm_group.num_joints]
                    tau = np.asarray(tau, dtype=np.float64) * self.config.gravity_compensation_scale
                except Exception:
                    if not self._gravity_warning_logged:
                        logger.exception(
                            "reBot RS gravity compensation failed; sending zero feed-forward torque."
                        )
                        self._gravity_warning_logged = True
            self._arm_group.send_mit(q_command, tau=tau)
        else:
            self._arm_group.send_pos_vel(q_command)
        if self._has_gripper and self._gripper_group is not None:
            with self._target_lock:
                gripper_target = self._gripper_target
            self._gripper_group.send_mit(np.array([gripper_target], dtype=np.float64))
        with self._latency_lock:
            self._control_callback_ms = (time.perf_counter() - callback_started) * 1e3

    def get_latency_snapshot(self) -> dict[str, float | int | None]:
        """Return the latest IK/control/CAN diagnostic values."""

        with self._latency_lock:
            snapshot: dict[str, float | int | None] = {
                "ik_queue_ms": self._ik_last_queue_ms,
                "ik_solve_ms": self._last_ik_duration_s * 1e3
                if self._last_ik_duration_s is not None
                else None,
                "ik_iterations": self._ik_last_iterations,
                "ik_request_seq": self._ik_last_seq,
                "ik_latest_seq": self._ik_last_latest_seq,
                "ik_published_total": self._ik_published_results,
                "ik_dropped_total": self._ik_dropped_results,
                "control_callback_ms": self._control_callback_ms,
                "command_actual_error_rad": self._last_command_actual_error_rad,
            }

        if self._arm is not None:
            diagnostics = getattr(self._arm, "get_diagnostics_snapshot", None)
            if callable(diagnostics):
                snapshot.update({f"can_{key}": value for key, value in diagnostics().items()})
        return snapshot

    def _start_ik_worker(self) -> None:
        """Start the single latest-target IK worker after hardware is ready."""

        with self._ik_condition:
            thread = self._ik_thread
            if thread is not None and thread.is_alive():
                return
            self._ik_stop_requested = False
            self._ik_request = None
            self._ik_thread = threading.Thread(
                target=self._ik_worker_loop,
                name="rebot-rs-ik-worker",
                daemon=True,
            )
            self._ik_thread.start()

    def _stop_ik_worker(self) -> None:
        """Stop the IK worker before the SDK/model resources are released."""

        with self._ik_condition:
            self._ik_stop_requested = True
            self._ik_request = None
            self._ik_request_times.clear()
            self._ik_epoch += 1
            self._ik_request_seq += 1
            self._ik_condition.notify_all()

        thread = self._ik_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("reBot RS IK worker did not stop within 5 seconds.")
        self._ik_thread = None

    def _invalidate_ik_requests(self) -> None:
        """Start a new IK epoch, e.g. before an explicit homing trajectory.

        Request sequence numbers describe input ordering within one continuous
        teleoperation epoch.  The epoch is the invalidation boundary used for
        homing, reset, mode changes, and shutdown.
        """

        with self._ik_condition:
            self._ik_request = None
            self._ik_request_times.clear()
            self._ik_epoch += 1
            self._ik_request_seq += 1

    def _ik_worker_loop(self) -> None:
        """Solve only the newest pending TCP target in a dedicated thread."""

        while True:
            with self._ik_condition:
                while self._ik_request is None and not self._ik_stop_requested:
                    self._ik_condition.wait()
                if self._ik_stop_requested:
                    return
                request_seq, request_epoch, target = self._ik_request
                self._ik_request = None
                submitted_at = self._ik_request_times.pop(request_seq, None)

            # Pinocchio ``Data`` is worker-owned.  The worker seed is updated
            # after every successful result that is published; the lifecycle
            # epoch remains the only invalidation boundary.
            with self._target_lock:
                q_seed = self._ik_worker_seed.copy()
                arm_group = self._arm_group
                sdk = self._sdk
                model = self._model
                data = self._data
                end_frame_id = self._end_frame_id

            if sdk is None or model is None or data is None or end_frame_id is None or arm_group is None:
                logger.warning("reBot RS IK request dropped because the solver is not ready.")
                continue

            params = sdk.IKParams(
                max_iter=self.config.ik_max_iter,
                tolerance=self.config.ik_tolerance,
                step_size=self.config.ik_step_size,
                damping=self.config.ik_damping,
            )
            solve_started = time.perf_counter()
            queue_ms = max(0.0, (solve_started - submitted_at) * 1e3) if submitted_at is not None else 0.0
            try:
                result = sdk.solve_ik(
                    model,
                    data,
                    end_frame_id,
                    target,
                    q_seed,
                    params,
                    controlled_joints=arm_group.num_joints,
                )
            except Exception:
                self._last_ik_duration_s = time.perf_counter() - solve_started
                with self._ik_condition:
                    latest_seq = self._ik_request_seq
                with self._latency_lock:
                    self._ik_last_queue_ms = queue_ms
                    self._ik_last_iterations = None
                    self._ik_last_seq = request_seq
                    self._ik_last_latest_seq = latest_seq
                if self._connected:
                    logger.exception("reBot RS asynchronous IK failed with an exception.")
                continue
            self._last_ik_duration_s = time.perf_counter() - solve_started

            if result.success:
                q_goal = np.asarray(result.q[: arm_group.num_joints], dtype=np.float64).copy()
                if not np.all(np.isfinite(q_goal)):
                    logger.warning("reBot RS asynchronous IK returned non-finite joint targets.")
                    self._last_ik_success = False
                    with self._ik_condition:
                        latest_seq = self._ik_request_seq
                    with self._latency_lock:
                        self._ik_last_queue_ms = queue_ms
                        self._ik_last_iterations = getattr(result, "iterations", None)
                        self._ik_last_seq = request_seq
                        self._ik_last_latest_seq = latest_seq
                    continue

                # A newer request in the same epoch does not invalidate this
                # completed result.  The mailbox is already latest-only, so
                # publishing this result prevents starvation when solve time
                # is longer than one teleoperation frame.  Only a lifecycle
                # epoch change invalidates a result (for example homing or
                # reset).
                with self._ik_condition:
                    latest_seq = self._ik_request_seq
                    if request_epoch != self._ik_epoch:
                        self._ik_dropped_results += 1
                        self._ik_dropped_epoch_results += 1
                        continue
                    with self._target_lock:
                        self._q_target = q_goal
                        self._q_seed = q_goal.copy()
                        self._ik_worker_seed = q_goal.copy()
                self._last_ik_success = True
                with self._latency_lock:
                    self._ik_last_queue_ms = queue_ms
                    self._ik_last_iterations = getattr(result, "iterations", None)
                    self._ik_last_seq = request_seq
                    self._ik_last_latest_seq = latest_seq
                    self._ik_published_results += 1
            else:
                with self._ik_condition:
                    latest_seq = self._ik_request_seq
                    if request_epoch != self._ik_epoch:
                        self._ik_dropped_results += 1
                        self._ik_dropped_epoch_results += 1
                        continue
                with self._latency_lock:
                    self._ik_last_queue_ms = queue_ms
                    self._ik_last_iterations = getattr(result, "iterations", None)
                    self._ik_last_seq = request_seq
                    self._ik_last_latest_seq = latest_seq
                if self._last_ik_success:
                    logger.warning(
                        "reBot RS asynchronous IK failed; holding previous joint target. err=%.3e",
                        result.error,
                    )
                self._last_ik_success = False

    def _action_to_target(self, action: RobotAction):
        pos = np.array([action["tcp.x"], action["tcp.y"], action["tcp.z"]], dtype=np.float64)
        r6d = np.array([action[f"tcp.r{i}"] for i in range(1, 7)], dtype=np.float64)
        rot = _rotation_6d_to_matrix(r6d)
        return self._sdk.pos_rot_to_se3(pos, rot=rot)

    def _gripper_from_action(self, action: RobotAction) -> float:
        raw = float(action.get("gripper.pos", 1.0))
        raw = float(np.clip(raw, 0.0, 1.0))
        return self.config.gripper_closed_pos + raw * (
            self.config.gripper_open_pos - self.config.gripper_closed_pos
        )

    def _normalize_gripper_position(self, position: float) -> float:
        """Map a physical gripper position to the dataset/control range [0, 1]."""
        closed = float(self.config.gripper_closed_pos)
        opened = float(self.config.gripper_open_pos)
        if opened == closed:
            raise ValueError("gripper_open_pos and gripper_closed_pos must be different")
        normalized = (float(position) - closed) / (opened - closed)
        return float(np.clip(normalized, 0.0, 1.0))

    def _read_camera_frame(self, cam_key: str):
        camera = self.cameras[cam_key]

        # Peek the camera's latest buffer directly. The camera backend already
        # runs its own background capture thread, so the control loop never waits
        # for a fresh frame here.
        frame = None
        timestamp = None
        try:
            if (
                hasattr(camera, "frame_lock")
                and hasattr(camera, "latest_frame")
                and hasattr(camera, "latest_timestamp")
            ):
                with camera.frame_lock:
                    frame = camera.latest_frame
                    timestamp = camera.latest_timestamp
            else:
                frame = camera.read_latest(max_age_ms=self._camera_max_age_ms)
        except (TimeoutError, RuntimeError) as exc:
            logger.debug("reBot RS camera %s frame unavailable: %s", cam_key, exc)
            return None

        if frame is None:
            return None

        if timestamp is not None:
            age_ms = (time.perf_counter() - timestamp) * 1e3
            if age_ms > self._camera_max_age_ms:
                if cam_key not in self._stale_camera_warnings:
                    logger.warning(
                        "reBot RS camera %s frame is stale: %.1f ms (max %d ms).",
                        cam_key,
                        age_ms,
                        self._camera_max_age_ms,
                    )
                    self._stale_camera_warnings.add(cam_key)
            else:
                self._stale_camera_warnings.discard(cam_key)

        return frame

    def _collect_observation(self) -> RobotObservation:
        q = self._read_arm_positions(request_feedback=False)
        with self._target_lock:
            q_command = self._q_command.copy()
        with self._latency_lock:
            self._last_command_actual_error_rad = (
                float(np.max(np.abs(q_command[: len(q)] - q))) if len(q) else None
            )
        q_padded = self._sdk.pad_q_for_model(self._model, q, len(q))
        tcp_pos, _, tcp_matrix = self._sdk.compute_fk(self._model, q_padded)
        rotation = np.asarray(tcp_matrix, dtype=np.float64)[:3, :3]
        # Continuous 6D rotation representation: first two matrix columns.
        rotation_6d = rotation[:, :2].T.reshape(6)
        gripper_pos = self._normalize_gripper_position(self._read_gripper_position(request_feedback=False))

        obs: RobotObservation = {
            "tcp.x": float(tcp_pos[0]),
            "tcp.y": float(tcp_pos[1]),
            "tcp.z": float(tcp_pos[2]),
            **{f"tcp.r{i + 1}": float(value) for i, value in enumerate(rotation_6d)},
            "gripper.pos": gripper_pos,
        }

        for cam_key, cam in self.cameras.items():
            if getattr(self.config.cameras[cam_key], "use_rgb", True):
                frame = self._read_camera_frame(cam_key)
                if frame is not None:
                    obs[cam_key] = frame
            if getattr(self.config.cameras[cam_key], "use_depth", False):
                try:
                    obs[f"{cam_key}_depth"] = cam.read_latest_depth()
                except (TimeoutError, RuntimeError) as exc:
                    logger.debug("reBot RS camera %s depth unavailable: %s", cam_key, exc)

        return obs

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        return self._collect_observation()

    def get_current_tcp_pose_quat(self) -> np.ndarray:
        q = self._read_arm_positions(request_feedback=False)
        q_padded = self._sdk.pad_q_for_model(self._model, q, len(q))
        _, _, tcp_matrix = self._sdk.compute_fk(self._model, q_padded)
        pose = matrix_to_pose7d(tcp_matrix, output_format="wxyz")
        return np.array([*pose, self._read_gripper_position(request_feedback=False)], dtype=np.float32)

    def _move_to_joint_target(
        self,
        target: np.ndarray,
        *,
        label: str,
        max_vel: float = 0.5,
        send_freq: float = 50.0,
        settle_thresh: float = 0.01,
        timeout: float = 15.0,
        gripper_target: float | None = None,
        cancel_event: threading.Event | None = None,
        settle_timeout: float = 3.0,
    ) -> bool:
        # A camera or teleoperator can fail after the actuator control loop has
        # already started. In that partial-startup state ``is_connected`` may
        # be false even though it is still possible (and required) to return
        # the arm to home before disabling the drives.
        if (
            self._arm is None
            or self._arm_group is None
            or not getattr(self._arm, "control_loop_active", False)
        ):
            logger.warning("Cannot move to %s: actuator control loop is not active", label)
            return False

        # Explicit point-to-point moves must invalidate any in-flight teleop
        # IK result so it cannot overwrite the homing/start trajectory.
        self._invalidate_ik_requests()

        q_now = self._read_arm_positions(request_feedback=True)
        n = len(q_now)
        if n == 0:
            logger.warning("Cannot move to %s: no joint feedback is available", label)
            return False

        q_target = np.asarray(target[:n], dtype=np.float64)
        if gripper_target is not None and self._has_gripper:
            self._gripper_target = float(gripper_target)

        max_err = float(np.max(np.abs(q_target - q_now)))
        if max_err < settle_thresh:
            with self._target_lock:
                self._q_target = q_target.copy()
                self._q_command = q_target.copy()
                self._q_velocity.fill(0.0)
                self._last_interp_time = None
                self._q_seed = q_target.copy()
                self._ik_worker_seed = q_target.copy()
            logger.info("reBot RS already at %s.", label)
            return True

        t_total = max(2.0 * max_err / max_vel, 0.5)
        num_steps = max(2, int(round(t_total * send_freq)))
        s = np.linspace(0.0, 1.0, num_steps)
        curve = 10.0 * s**3 - 15.0 * s**4 + 6.0 * s**5

        traj = np.zeros((num_steps, n), dtype=np.float64)
        for i in range(n):
            traj[:, i] = q_now[i] + (q_target[i] - q_now[i]) * curve

        logger.info("reBot RS moving to %s...", label)
        deadline = time.monotonic() + timeout
        sleep_s = 1.0 / send_freq
        for q_cmd in traj:
            if cancel_event is not None and cancel_event.is_set():
                logger.warning("Move to %s cancelled before reaching the target", label)
                self._invalidate_ik_requests()
                return False
            if time.monotonic() > deadline:
                logger.warning("reBot RS move to %s timed out before reaching target.", label)
                self._invalidate_ik_requests()
                return False
            with self._target_lock:
                # Homing is an explicit point-to-point operation. Keep the
                # sent command and newest goal synchronized so teleop
                # interpolation cannot slow or overwrite the homing segment.
                self._q_target = q_cmd.copy()
                self._q_command = q_cmd.copy()
                self._q_velocity.fill(0.0)
                self._last_interp_time = None
            with self._target_lock:
                self._q_seed = q_cmd.copy()
                self._ik_worker_seed = q_cmd.copy()
            time.sleep(sleep_s)

        with self._target_lock:
            self._q_target = q_target.copy()
            self._q_command = q_target.copy()
            self._q_velocity.fill(0.0)
            self._last_interp_time = None
        with self._target_lock:
            self._q_seed = q_target.copy()
            self._ik_worker_seed = q_target.copy()

        settle_deadline = time.monotonic() + settle_timeout
        last_error = float("inf")
        while time.monotonic() < settle_deadline:
            if cancel_event is not None and cancel_event.is_set():
                logger.warning("Move to %s cancelled while waiting for settling", label)
                self._invalidate_ik_requests()
                return False
            q_now = self._read_arm_positions(request_feedback=True)
            last_error = float(np.max(np.abs(q_now[:n] - q_target[:n])))
            if last_error < settle_thresh:
                # Discard any teleoperation request that may have arrived while the explicit
                # point-to-point move was running. The next frame starts a fresh epoch.
                self._invalidate_ik_requests()
                logger.info("reBot RS reached %s.", label)
                return True
            time.sleep(0.02)

        # Discard any teleoperation request that may have arrived while the
        # explicit point-to-point move was running.  The next teleop frame will
        # start a fresh epoch from this settled seed.
        self._invalidate_ik_requests()
        logger.warning(
            "reBot RS did not reach %s within the settling timeout (max joint error %.4f rad, tolerance %.4f)",
            label,
            last_error,
            settle_thresh,
        )
        return False

    def safe_home(
        self,
        *,
        max_vel: float = 0.5,
        send_freq: float = 50.0,
        settle_thresh: float = 0.01,
        timeout: float = 15.0,
        open_gripper: bool = False,
    ) -> bool:
        """Move the arm back to the mechanical zero pose before shutdown."""

        home = np.asarray(self.config.home_position[:6], dtype=np.float64)
        gripper_target = (
            float(self.config.gripper_open_pos) if open_gripper else float(self.config.home_position[6])
        )
        return self._move_to_joint_target(
            home,
            label="mechanical home",
            max_vel=max_vel,
            send_freq=send_freq,
            settle_thresh=settle_thresh,
            timeout=timeout,
            gripper_target=gripper_target,
        )

    def go_to_start_position(
        self,
        *,
        max_vel: float = 0.5,
        send_freq: float = 50.0,
        settle_thresh: float | None = None,
        timeout: float = 15.0,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Move the arm to the configured start pose."""

        start = np.asarray(self.config.start_position[:6], dtype=np.float64)
        settle_thresh = self.config.start_position_settle_thresh if settle_thresh is None else settle_thresh
        return self._move_to_joint_target(
            start,
            label="start pose",
            max_vel=max_vel,
            send_freq=send_freq,
            settle_thresh=settle_thresh,
            timeout=timeout,
            gripper_target=float(self.config.start_position[6]),
            cancel_event=cancel_event,
            settle_timeout=self.config.start_position_settle_timeout_s,
        )

    def reset_to_initial_position(self) -> bool:
        """Compatibility alias used by the teleop loop for A-button homing."""
        return self.go_to_start_position()

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        missing = [key for key in TCP_ACTION_KEYS if key not in action]
        if missing:
            raise ValueError(f"Missing rebot_rs_follower action keys: {missing}")

        canonical_action = {key: float(action[key]) for key in TCP_ACTION_KEYS}
        canonical_action["gripper.pos"] = float(np.clip(canonical_action["gripper.pos"], 0.0, 1.0))

        target = self._action_to_target(canonical_action)
        gripper_target = self._gripper_from_action(canonical_action)

        # Do not solve IK on the teleoperation thread.  Replace the mailbox
        # contents so a slow solve can never make old hand poses accumulate.
        with self._ik_condition:
            previous_request = self._ik_request
            self._ik_request_seq += 1
            if previous_request is not None:
                self._ik_request_times.pop(previous_request[0], None)
            self._ik_request_times[self._ik_request_seq] = time.perf_counter()
            self._ik_request = (self._ik_request_seq, self._ik_epoch, target)
            self._ik_condition.notify()
        with self._target_lock:
            self._gripper_target = gripper_target
        return canonical_action

    def disconnect(self) -> None:
        """Stop motion and release hardware, including partial connections.

        This method is intentionally idempotent and is not guarded by
        ``check_if_not_connected``. Startup failures can leave the actuator
        object and control loop alive before ``_connected`` is set.
        """

        arm = self._arm
        self._connected = False

        self._stop_position_compare_diagnostic()

        # Stop asynchronous IK before releasing the model/data or actuator
        # resources it may be using.
        self._stop_ik_worker()

        if arm is not None and hasattr(arm, "stop_feedback_loop"):
            try:
                arm.stop_feedback_loop()
            except Exception as exc:
                logger.warning("Failed to stop reBot RS feedback loop: %s", exc)

        if arm is not None and hasattr(arm, "stop_control_loop"):
            try:
                arm.stop_control_loop()
            except Exception as exc:
                logger.warning("Failed to stop reBot RS control loop: %s", exc)

        # RebotArm.disconnect() disables all motor groups before closing the
        # CAN controllers. Keep this step even if stopping a worker failed.
        if arm is not None:
            try:
                time.sleep(0.1)
                arm.disconnect()
            except Exception as exc:
                logger.warning("Failed to disconnect reBot RS actuator: %s", exc)

        for camera in self.cameras.values():
            try:
                camera.disconnect()
            except Exception as exc:
                logger.warning("Failed to disconnect reBot RS camera: %s", exc)

        self._arm = None
        self._arm_group = None
        self._gripper_group = None
        self._dynamics_data = None
        logger.info("%s disconnected.", self)
