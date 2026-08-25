# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
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

"""
Simple script to control a robot from teleoperation.

Requires: pip install 'lerobot[hardware]'

Example:

```shell
lerobot-teleoperate \
    --robot.type=so101_follower \
    --robot.port=/dev/tty.usbmodem58760431541 \
    --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30}}" \
    --robot.id=black \
    --teleop.type=so101_leader \
    --teleop.port=/dev/tty.usbmodem58760431551 \
    --teleop.id=blue \
    --display_data=true
```

To stream the data to Foxglove instead of Rerun, add ``--display_mode=foxglove``
(then connect the Foxglove app to ``ws://127.0.0.1:8765``; override the port with ``--display_port=<port>``):

```shell
lerobot-teleoperate \
    --robot.type=so101_follower \
    --robot.port=/dev/tty.usbmodem58760431541 \
    --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30}}" \
    --robot.id=black \
    --teleop.type=so101_leader \
    --teleop.port=/dev/tty.usbmodem58760431551 \
    --teleop.id=blue \
    --display_data=true \
    --display_mode=foxglove
```

Example teleoperation with bimanual so100:

```shell
lerobot-teleoperate \
  --robot.type=bi_so_follower \
  --robot.left_arm_config.port=/dev/tty.usbmodem5A460822851 \
  --robot.right_arm_config.port=/dev/tty.usbmodem5A460814411 \
  --robot.id=bimanual_follower \
  --robot.left_arm_config.cameras='{
    wrist: {"type": "opencv", "index_or_path": 1, "width": 640, "height": 480, "fps": 30},
  }' --robot.right_arm_config.cameras='{
    wrist: {"type": "opencv", "index_or_path": 2, "width": 640, "height": 480, "fps": 30},
  }' \
  --teleop.type=bi_so_leader \
  --teleop.left_arm_config.port=/dev/tty.usbmodem5A460852721 \
  --teleop.right_arm_config.port=/dev/tty.usbmodem5A460819811 \
  --teleop.id=bimanual_leader \
  --display_data=true
```

"""

import logging
import sys
import time
from dataclasses import asdict, dataclass
from pprint import pformat

from lerobot.cameras.opencv import OpenCVCameraConfig  # noqa: F401
from lerobot.cameras.realsense import RealSenseCameraConfig  # noqa: F401
from lerobot.cameras.zmq import ZMQCameraConfig  # noqa: F401
from lerobot.configs import parser
from lerobot.processor import (
    RobotAction,
    RobotObservation,
    RobotProcessorPipeline,
    make_default_processors,
)
from lerobot.robots import (  # noqa: F401
    Robot,
    RobotConfig,
    bi_openarm_follower,
    bi_rebot_b601_follower,
    bi_so_follower,
    earthrover_mini_plus,
    hope_jr,
    koch_follower,
    make_robot_from_config,
    omx_follower,
    openarm_follower,
    reachy2,
    rebot_b601_follower,
    rebot_rs_follower,
    so_follower,
    unitree_g1 as unitree_g1_robot,
)
from lerobot.teleoperators import (  # noqa: F401
    Teleoperator,
    TeleoperatorConfig,
    bi_openarm_leader,
    bi_openarm_mini,
    bi_pico4,
    bi_rebot_102_leader,
    bi_so_leader,
    gamepad,
    homunculus,
    keyboard,
    koch_leader,
    make_teleoperator_from_config,
    omx_leader,
    openarm_leader,
    openarm_mini,
    pico4,
    reachy2_teleoperator,
    rebot_102_leader,
    so_leader,
    unitree_g1,
)
from lerobot.teleoperators.pico4.rebot_b601_bridge import RebotB601PicoTeleopSession
from lerobot.utils.cycle_timer import CycleTimer
from lerobot.utils.import_utils import register_third_party_plugins
from lerobot.utils.utils import init_logging, move_cursor_up
from lerobot.utils.visualization_utils import (
    init_visualization,
    log_visualization_data,
    shutdown_visualization,
)


logger = logging.getLogger(__name__)


def _render_terminal_dashboard(lines: list[str]) -> None:
    """Render one complete dashboard frame without cursor-relative updates."""

    frame = "\n".join(lines)
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(frame)
        sys.stdout.write("\033[J\n")
    else:
        # Captured/non-interactive output should not contain cursor controls.
        sys.stdout.write(frame + "\n")
    sys.stdout.flush()


@dataclass
class TeleoperateConfig:
    # TODO: pepijn, steven: if more robots require multiple teleoperators (like lekiwi) its good to make this possibele in teleop.py and record.py with List[Teleoperator]
    teleop: TeleoperatorConfig
    robot: RobotConfig
    # Limit the maximum frames per second.
    fps: int = 60
    teleop_time_s: float | None = None
    # Build devices and validate configs without connecting or sending actions.
    dryrun: bool = False
    # Display all cameras on screen
    display_data: bool = False
    # Visualization backend used when display_data is True: "rerun" or "foxglove".
    display_mode: str = "rerun"
    # For "rerun": IP of a remote server to send to. For "foxglove": interface to bind the WebSocket
    # server to (127.0.0.1 for local only, 0.0.0.0 for all interfaces).
    display_ip: str | None = None
    # For "rerun": port of the remote server. For "foxglove": port to bind the WebSocket server to.
    display_port: int | None = None
    # Whether to display compressed (JPEG) images instead of raw frames
    display_compressed_images: bool = False


def teleop_loop(
    teleop: Teleoperator,
    robot: Robot,
    fps: int,
    teleop_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_observation_processor: RobotProcessorPipeline[RobotObservation, RobotObservation],
    display_data: bool = False,
    display_mode: str = "rerun",
    duration: float | None = None,
    display_compressed_images: bool = False,
):
    """
    This function continuously reads actions from a teleoperation device, processes them through optional
    pipelines, sends them to a robot, and optionally displays the robot's state. The loop runs at a
    specified frequency until a set duration is reached or it is manually interrupted.

    Args:
        teleop: The teleoperator device instance providing control actions.
        robot: The robot instance being controlled.
        fps: The target frequency for the control loop in frames per second.
        display_data: If True, fetches robot observations and displays them in the console and the
            visualization backend.
        display_mode: Visualization backend to use when display_data is True ("rerun" or "foxglove").
        display_compressed_images: If True, compresses images before sending them to the backend for display.
        duration: The maximum duration of the teleoperation loop in seconds. If None, the loop runs indefinitely.
        teleop_action_processor: An optional pipeline to process raw actions from the teleoperator.
        robot_action_processor: An optional pipeline to process actions before they are sent to the robot.
        robot_observation_processor: An optional pipeline to process raw observations from the robot.
    """

    display_len = max(len(key) for key in robot.action_features)
    # Teleoperation writes no dataset, so a missed deadline costs control smoothness
    # only.  The live readout below is the instantaneous rate; the timer adds the
    # warning when the loop cannot keep up and the summary of where the time went.
    timer = CycleTimer(fps, records_data=False)
    start = time.perf_counter()
    try:
        while True:
            timer.tick()
            loop_start = time.perf_counter()  # for the live readout below

            with timer.section("observe"):
                # Get robot observation
                # Not really needed for now other than for visualization
                # teleop_action_processor can take None as an observation
                # given that it is the identity processor as default
                obs = robot.get_observation()

                if robot.name == "unitree_g1":
                    teleop.send_feedback(obs)

            with timer.section("teleop"):
                # Get teleop action
                raw_action = teleop.get_action()

                # Process teleop action through pipeline
                teleop_action = teleop_action_processor((raw_action, obs))

                # Process action for robot through pipeline
                robot_action_to_send = robot_action_processor((teleop_action, obs))

            with timer.section("send"):
                # Send processed action to robot (robot_action_processor.to_output should return RobotAction)
                _ = robot.send_action(robot_action_to_send)

            if display_data:
                with timer.section("telemetry"):
                    # Process robot observation through pipeline
                    obs_transition = robot_observation_processor(obs)

                    log_visualization_data(
                        display_mode,
                        observation=obs_transition,
                        action=teleop_action,
                        compress_images=display_compressed_images,
                    )

                    print("\n" + "-" * (display_len + 10))
                    print(f"{'NAME':<{display_len}} | {'NORM':>7}")
                    # Display the final robot action that was sent
                    for motor, value in robot_action_to_send.items():
                        print(f"{motor:<{display_len}} | {value:>7.2f}")
                    move_cursor_up(len(robot_action_to_send) + 3)

            timer.wait()
            loop_s = time.perf_counter() - loop_start
            print(f"Teleop loop time: {loop_s * 1e3:.2f}ms ({1 / loop_s:.0f} Hz)")
            move_cursor_up(1)

            if duration is not None and time.perf_counter() - start >= duration:
                return
    finally:
        # In `finally` so ^C — how a teleop session normally ends — still reports.
        timer.log_run_summary()


def rebot_b601_pico4_teleop_loop(
    teleop: Teleoperator,
    robot: Robot,
    fps: int,
    robot_observation_processor: RobotProcessorPipeline[RobotObservation, RobotObservation],
    display_data: bool = False,
    display_mode: str = "rerun",
    duration: float | None = None,
    display_compressed_images: bool = False,
):
    """Teleoperate a reBot B601 follower with a Pico4 controller."""

    display_len = max(len(key) for key in robot.action_features)
    timer = CycleTimer(fps, records_data=False)
    start = time.perf_counter()
    session = RebotB601PicoTeleopSession()
    was_enabled = False

    try:
        joints = RebotB601PicoTeleopSession.extract_joint_positions(robot.get_observation())
        neutral_pose = RebotB601PicoTeleopSession.pico_neutral_pose(joints.get("gripper", 0.0))
        teleop.connect(current_tcp_pose_quat=neutral_pose)
        session.sync(joints, teleop.get_action())
        logging.info("Pico4 + reBot B601 teleop session ready.")

        while True:
            timer.tick()
            loop_start = time.perf_counter()

            with timer.section("observe"):
                obs = robot.get_observation()

            with timer.section("teleop"):
                raw_action = teleop.get_action()
                enabled = teleop.is_enabled

                if teleop.get_reset_button():
                    session.sync(RebotB601PicoTeleopSession.extract_joint_positions(obs), raw_action)
                    logging.info("reBot B601 anchors resynced from current robot pose.")
                elif enabled and not was_enabled:
                    session.sync(RebotB601PicoTeleopSession.extract_joint_positions(obs), raw_action)

                if enabled and session.joint_anchor is not None:
                    robot_action_to_send = session.build_action(raw_action)
                else:
                    robot_action_to_send = session.build_hold_action(raw_action)

                was_enabled = enabled

            with timer.section("send"):
                _ = robot.send_action(robot_action_to_send)

            if display_data:
                with timer.section("telemetry"):
                    obs_transition = robot_observation_processor(obs)

                    log_visualization_data(
                        display_mode,
                        observation=obs_transition,
                        action=robot_action_to_send,
                        compress_images=display_compressed_images,
                    )

                    print("\n" + "-" * (display_len + 10))
                    print(f"{'NAME':<{display_len}} | {'NORM':>7}")
                    for motor, value in robot_action_to_send.items():
                        print(f"{motor:<{display_len}} | {value:>7.2f}")
                    move_cursor_up(len(robot_action_to_send) + 3)

            timer.wait()
            loop_s = time.perf_counter() - loop_start
            print(f"Teleop loop time: {loop_s * 1e3:.2f}ms ({1 / loop_s:.0f} Hz)")
            move_cursor_up(1)

            if duration is not None and time.perf_counter() - start >= duration:
                return
    finally:
        timer.log_run_summary()


def _rebot_rs_start_pico4(teleop: Teleoperator, robot: Robot, *, dryrun: bool = False) -> None:
    if dryrun:
        logging.info("[DRYRUN] Pico4 A button start request: reBot RS would return to the start pose.")
        return

    robot.reset_to_initial_position()
    current_pose = robot.get_current_tcp_pose_quat()
    teleop.reset_to_pose(current_pose[:7], float(current_pose[7]))
    logging.info("Pico4 A button start: reBot RS returned to the start pose.")


def rebot_rs_pico4_teleop_loop(
    teleop: Teleoperator,
    robot: Robot,
    fps: int,
    teleop_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_observation_processor: RobotProcessorPipeline[RobotObservation, RobotObservation],
    display_data: bool = False,
    display_mode: str = "rerun",
    duration: float | None = None,
    display_compressed_images: bool = False,
    dryrun: bool = False,
):
    """Pico4 + reBot RS teleop loop with A-button reset and optional dry-run."""

    display_len = max(len(key) for key in robot.action_features)
    timer = CycleTimer(fps, records_data=False)
    start = time.perf_counter()
    last_latency_log = time.monotonic()
    last_action_log = last_latency_log
    last_latency_log_counters = {"published": 0, "dropped": 0, "send_errors": 0}

    def _fmt_latency(value, suffix: str = "ms") -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.1f}{suffix}"

    try:
        while True:
            timer.tick()
            loop_start = time.perf_counter()

            observe_started = time.perf_counter()
            with timer.section("observe"):
                obs = robot.get_observation()
            observe_ms = (time.perf_counter() - observe_started) * 1e3

            teleop_started = time.perf_counter()
            with timer.section("teleop"):
                raw_action = teleop.get_action()
                if teleop.get_reset_button():
                    _rebot_rs_start_pico4(teleop, robot, dryrun=dryrun)
                    if display_data:
                        with timer.section("telemetry"):
                            obs_transition = robot_observation_processor(obs)
                            log_visualization_data(
                                display_mode,
                                observation=obs_transition,
                                compress_images=display_compressed_images,
                            )
                    timer.wait()
                    loop_s = time.perf_counter() - loop_start
                    reset_tag = "[DRYRUN] " if dryrun else ""
                    reset_line = f"{reset_tag}{loop_s * 1e3:5.2f}ms ({1 / loop_s:.0f} Hz) | A start"
                    if display_data:
                        _render_terminal_dashboard([reset_line])
                    else:
                        print(f"\r\033[K{reset_line}", end="", flush=True)
                    if duration is not None and time.perf_counter() - start >= duration:
                        return
                    continue
                teleop_action = teleop_action_processor((raw_action, obs))
                robot_action_to_send = robot_action_processor((teleop_action, obs))
                action_summary = " ".join(f"{k}={float(v):+.4f}" for k, v in robot_action_to_send.items())
            teleop_ms = (time.perf_counter() - teleop_started) * 1e3

            send_started = time.perf_counter()
            with timer.section("send"):
                if not dryrun:
                    _ = robot.send_action(robot_action_to_send)
            send_ms = (time.perf_counter() - send_started) * 1e3

            # Print a compact diagnostic summary every 0.5 s rather than
            # flooding the terminal at the teleoperation rate.
            now = time.monotonic()
            if now - last_latency_log >= 0.5:
                pico_snapshot = getattr(teleop, "get_latency_snapshot", lambda: {})()
                robot_snapshot = getattr(robot, "get_latency_snapshot", lambda: {})()
                elapsed = now - last_latency_log
                published = int(robot_snapshot.get("ik_published_total", 0) or 0)
                dropped = int(robot_snapshot.get("ik_dropped_total", 0) or 0)
                send_errors = int(robot_snapshot.get("can_send_errors", 0) or 0)
                request_seq = robot_snapshot.get("ik_request_seq")
                latest_seq = robot_snapshot.get("ik_latest_seq")
                seq_lag = (
                    int(latest_seq) - int(request_seq)
                    if latest_seq is not None and request_seq is not None
                    else "n/a"
                )
                logger.info(
                    "[LATENCY] loop=%s observe=%s teleop=%s send=%s | "
                    "PICO age=%s sdk=%s process=%s dup=%d | "
                    "IK queue=%s solve=%s iter=%s seq=%s latest=%s lag=%s pub=%.1f/s drop=%.1f/s | "
                    "control=%s qerr=%s | CAN send_err=%.1f/s feedback=%s cache=%s",
                    _fmt_latency((time.perf_counter() - loop_start) * 1e3),
                    _fmt_latency(observe_ms),
                    _fmt_latency(teleop_ms),
                    _fmt_latency(send_ms),
                    _fmt_latency(pico_snapshot.get("pico_age_ms")),
                    _fmt_latency(pico_snapshot.get("sdk_getters_ms")),
                    _fmt_latency(pico_snapshot.get("processing_ms")),
                    int(pico_snapshot.get("pico_duplicate_frames", 0) or 0),
                    _fmt_latency(robot_snapshot.get("ik_queue_ms")),
                    _fmt_latency(robot_snapshot.get("ik_solve_ms")),
                    robot_snapshot.get("ik_iterations", "n/a"),
                    request_seq if request_seq is not None else "n/a",
                    latest_seq if latest_seq is not None else "n/a",
                    seq_lag,
                    (published - last_latency_log_counters["published"]) / elapsed,
                    (dropped - last_latency_log_counters["dropped"]) / elapsed,
                    _fmt_latency(robot_snapshot.get("control_callback_ms")),
                    _fmt_latency(robot_snapshot.get("command_actual_error_rad"), "rad"),
                    (send_errors - last_latency_log_counters["send_errors"]) / elapsed,
                    _fmt_latency(robot_snapshot.get("can_feedback_last_sweep_ms")),
                    _fmt_latency(robot_snapshot.get("can_feedback_cache_age_ms")),
                )
                last_latency_log = now
                last_latency_log_counters = {
                    "published": published,
                    "dropped": dropped,
                    "send_errors": send_errors,
                }

            dashboard_lines: list[str] | None = None
            if display_data:
                with timer.section("telemetry"):
                    obs_transition = robot_observation_processor(obs)
                    log_visualization_data(
                        display_mode,
                        observation=obs_transition,
                        action=teleop_action,
                        compress_images=display_compressed_images,
                    )

                    dashboard_lines = [
                        "-" * (display_len + 18),
                        f"{'NAME':<{display_len}} | {'PICO RAW':>10}",
                    ]
                    for key, value in teleop_action.items():
                        dashboard_lines.append(f"{key:<{display_len}} | {value:>10.4f}")
                    dashboard_lines.append("-" * (display_len + 18))
                    preview_label = "robot action preview (not sent)" if dryrun else "robot action"
                    dashboard_lines.append(f"[{preview_label}]")
                    for key, value in robot_action_to_send.items():
                        dashboard_lines.append(f"  {key}: {value:.4f}")

            timer.wait()
            loop_s = time.perf_counter() - loop_start
            if display_data:
                _render_terminal_dashboard(
                    (dashboard_lines or []) + [f"loop: {loop_s * 1e3:5.2f} ms ({1 / loop_s:.0f} Hz)"]
                )
            else:
                tag = "[DRYRUN] " if dryrun else ""
                # Action values are useful for diagnosis, but printing them at
                # the 30 Hz teleoperation cadence overwhelms the terminal.
                # Keep the control loop unchanged and emit the latest values
                # once per second.
                now = time.monotonic()
                if now - last_action_log >= 1.0:
                    print(f"{tag}{loop_s * 1e3:5.2f}ms ({1 / loop_s:.0f} Hz) | {action_summary}", flush=True)
                    last_action_log = now

            if duration is not None and time.perf_counter() - start >= duration:
                return
    finally:
        timer.log_run_summary()


def rebot_rs_pico4_dryrun_loop(
    teleop: Teleoperator,
    robot: Robot,
    fps: int,
    teleop_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_action_processor: RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction],
    robot_observation_processor: RobotProcessorPipeline[RobotObservation, RobotObservation],
    display_data: bool = False,
    display_mode: str = "rerun",
    duration: float | None = None,
    display_compressed_images: bool = False,
):
    """Dry-run Pico4 + reBot RS by printing Pico actions without sending them to the robot."""

    rebot_rs_pico4_teleop_loop(
        teleop=teleop,
        robot=robot,
        fps=fps,
        teleop_action_processor=teleop_action_processor,
        robot_action_processor=robot_action_processor,
        robot_observation_processor=robot_observation_processor,
        display_data=display_data,
        display_mode=display_mode,
        duration=duration,
        display_compressed_images=display_compressed_images,
        dryrun=True,
    )


def _device_is_connected(device) -> bool:
    try:
        return bool(device.is_connected)
    except Exception:
        return False


def _rebot_rs_resources_present(robot) -> bool:
    """Return whether a reBot RS object may still own actuator resources."""

    return _device_is_connected(robot) or getattr(robot, "_arm", None) is not None


def _cleanup_teleoperate_session(
    *,
    teleop: Teleoperator,
    robot: Robot,
    special_rebot_rs_pico4: bool,
    dryrun: bool,
) -> None:
    """Best-effort shutdown with reBot RS homing before drive disable.

    This helper is called from a ``finally`` that also covers startup. It must
    never let a cleanup failure prevent the remaining disconnect steps.
    """

    robot_resources = (
        _rebot_rs_resources_present(robot)
        if special_rebot_rs_pico4
        else _device_is_connected(robot)
    )

    if special_rebot_rs_pico4 and robot_resources and not dryrun:
        try:
            robot.safe_home()
        except Exception as exc:
            logger.warning("Failed to home reBot RS before shutdown: %s", exc)

    if _device_is_connected(teleop):
        try:
            teleop.disconnect()
        except Exception as exc:
            logger.warning("Failed to disconnect teleop cleanly: %s", exc)

    # RebotRSFollower.disconnect() is idempotent and also handles a partial
    # startup, so call it whenever its actuator object exists. Other robots
    # retain the normal is_connected guard.
    if robot_resources:
        try:
            robot.disconnect()
        except Exception as exc:
            logger.warning("Failed to disconnect robot cleanly: %s", exc)


@parser.wrap()
def teleoperate(cfg: TeleoperateConfig):
    init_logging()
    logging.info(pformat(asdict(cfg)))
    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()

    if cfg.dryrun:
        teleop = make_teleoperator_from_config(cfg.teleop)
        robot = make_robot_from_config(cfg.robot)
        special_rebot_rs_pico4 = robot.name == "rebot_rs_follower" and teleop.name == "pico4"

        if special_rebot_rs_pico4:
            if cfg.display_data:
                init_visualization(
                    cfg.display_mode, session_name="teleoperation", ip=cfg.display_ip, port=cfg.display_port
                )
            display_compressed_images = (
                True
                if (cfg.display_data and cfg.display_ip is not None and cfg.display_port is not None)
                else cfg.display_compressed_images
            )

            try:
                # Connect Pico first. A missing VR controller must not power
                # the robot just to discover that teleoperation cannot start.
                teleop.connect()
                robot.connect()
                current_pose = robot.get_current_tcp_pose_quat()
                teleop.reset_to_pose(current_pose[:7], float(current_pose[7]))
                rebot_rs_pico4_teleop_loop(
                    teleop=teleop,
                    robot=robot,
                    fps=cfg.fps,
                    display_data=cfg.display_data,
                    display_mode=cfg.display_mode,
                    duration=cfg.teleop_time_s,
                    teleop_action_processor=teleop_action_processor,
                    robot_action_processor=robot_action_processor,
                    robot_observation_processor=robot_observation_processor,
                    display_compressed_images=display_compressed_images,
                    dryrun=True,
                )
            finally:
                _cleanup_teleoperate_session(
                    teleop=teleop,
                    robot=robot,
                    special_rebot_rs_pico4=True,
                    dryrun=True,
                )
                if cfg.display_data:
                    shutdown_visualization(cfg.display_mode)
            return

        print("[dryrun] teleop:", type(teleop).__name__)
        print("[dryrun] robot:", type(robot).__name__)
        print("[dryrun] teleop action features:", teleop.action_features)
        print("[dryrun] robot action features:", robot.action_features)
        print("[dryrun] robot observation features:", robot.observation_features)
        return

    if cfg.display_data:
        init_visualization(
            cfg.display_mode, session_name="teleoperation", ip=cfg.display_ip, port=cfg.display_port
        )
    display_compressed_images = (
        True
        if (cfg.display_data and cfg.display_ip is not None and cfg.display_port is not None)
        else cfg.display_compressed_images
    )

    teleop = make_teleoperator_from_config(cfg.teleop)
    robot = make_robot_from_config(cfg.robot)

    special_rebot_pico4 = robot.name == "rebot_b601_follower" and teleop.name == "pico4"
    special_rebot_rs_pico4 = robot.name == "rebot_rs_follower" and teleop.name == "pico4"

    try:
        if special_rebot_pico4:
            robot.connect()
        elif special_rebot_rs_pico4:
            # The Pico connection is the gate for actuator power. Do this
            # before connecting RobStride, enabling drives, or moving home.
            teleop.connect()
            robot.connect()
            robot.safe_home()
            robot.go_to_start_position()
            current_pose = robot.get_current_tcp_pose_quat()
            teleop.reset_to_pose(current_pose[:7], float(current_pose[7]))
        else:
            teleop.connect()
            robot.connect()

        if special_rebot_pico4:
            rebot_b601_pico4_teleop_loop(
                teleop=teleop,
                robot=robot,
                fps=cfg.fps,
                display_data=cfg.display_data,
                display_mode=cfg.display_mode,
                duration=cfg.teleop_time_s,
                robot_observation_processor=robot_observation_processor,
                display_compressed_images=display_compressed_images,
            )
        elif special_rebot_rs_pico4:
            rebot_rs_pico4_teleop_loop(
                teleop=teleop,
                robot=robot,
                fps=cfg.fps,
                display_data=cfg.display_data,
                display_mode=cfg.display_mode,
                duration=cfg.teleop_time_s,
                teleop_action_processor=teleop_action_processor,
                robot_action_processor=robot_action_processor,
                robot_observation_processor=robot_observation_processor,
                display_compressed_images=display_compressed_images,
                dryrun=False,
            )
        else:
            teleop_loop(
                teleop=teleop,
                robot=robot,
                fps=cfg.fps,
                display_data=cfg.display_data,
                display_mode=cfg.display_mode,
                duration=cfg.teleop_time_s,
                teleop_action_processor=teleop_action_processor,
                robot_action_processor=robot_action_processor,
                robot_observation_processor=robot_observation_processor,
                display_compressed_images=display_compressed_images,
            )
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup_teleoperate_session(
            teleop=teleop,
            robot=robot,
            special_rebot_rs_pico4=special_rebot_rs_pico4,
            dryrun=cfg.dryrun,
        )
        if cfg.display_data:
            shutdown_visualization(cfg.display_mode)


def main():
    register_third_party_plugins()
    teleoperate()


if __name__ == "__main__":
    main()
