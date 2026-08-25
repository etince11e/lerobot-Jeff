# lerobot-Jeff

[中文](README-zh.md) | English

`lerobot-Jeff` is a real-robot teleoperation project that connects a PICO 4 VR controller to a reBot RS follower arm through the LeRobot control pipeline. It includes environment setup, PICO 4 input processing, reBot SDK integration, Cartesian-to-joint inverse kinematics, CAN motor control, optional cameras, and safe startup/shutdown handling.

The repository name is `lerobot-Jeff`. The Python package and command-line tools intentionally remain `lerobot`, so existing imports such as `import lerobot` and commands such as `lerobot-teleoperate` continue to work.

## Safety

The real-robot command powers the reBot drives and moves the arm automatically. Before every run:

- Clear the robot workspace and keep an emergency stop within reach.
- Verify the CAN channel, joint directions, zero positions, start pose, and home pose.
- Keep the PICO grip released until the arm reaches the configured start pose.
- Start with reduced PICO position and orientation sensitivity when testing a new setup.
- Use `Ctrl+C` for normal shutdown and wait for the arm to return home before removing power.

`--dryrun=true` is an action-preview mode, not a hardware-free simulation. It still connects the PICO device and reBot arm and may enable the drives, but it does not send the generated teleoperation actions.

## System Overview

```mermaid
flowchart LR
    A[PICO 4 headset and controller] --> B[PICO PC bridge service]
    B --> C[PICO Python SDK]
    C --> D[LeRobot Pico4 teleoperator]
    D -->|TCP pose and gripper action| E[LeRobot action pipeline]
    E --> F[reBot RS follower]
    F --> G[Latest-target asynchronous IK]
    G --> H[reBot control SDK]
    H --> I[CAN bus]
    I --> J[Arm and gripper motors]
```

The control action shared by both sides contains:

- `tcp.x`, `tcp.y`, `tcp.z`: absolute end-effector position in meters.
- `tcp.r1` through `tcp.r6`: continuous 6D end-effector rotation representation.
- `gripper.pos`: normalized gripper command in the range `[0, 1]`.

## Requirements

- Ubuntu 22.04 or newer.
- Python 3.12.
- Conda or Mamba; Miniforge is recommended.
- A PICO 4 headset with a paired controller and the PICO tracking client installed.
- A running PICO PC bridge service that can receive controller tracking data.
- A reBot RS arm, USB-CAN adapter, and a configured SocketCAN interface.
- The reBot and PICO SDK payloads required by this project under the repository's expected `third_party/` locations.
- Optional head and wrist cameras. The defaults are `/dev/video5` and `/dev/video3`.

Install basic system tools:

```bash
sudo apt update
sudo apt install -y build-essential git git-lfs iproute2 can-utils
```

## Environment Installation

Clone the repository and initialize both SDK submodules:

```bash
git clone --recurse-submodules https://github.com/YOUR_GITHUB_USER/lerobot-Jeff.git
cd lerobot-Jeff
git lfs install
git lfs pull
```

This repository keeps the reBot and XenseVR SDK sources as Git submodules:

- `third_party/reBotArm_control_py` — reBot arm SDK.
- `third_party/XenseVR-PC-Service` — XenseVR PC service and native SDK.

If you cloned the repository without `--recurse-submodules`, initialize the SDK directories before running the installation script:

```bash
git submodule update --init --recursive
```

You can verify that both submodules are checked out with:

```bash
git submodule status
```

Create a Python 3.12 environment with Mamba:

```bash
bash ./setup_env.sh --mamba lerobot-Jeff
mamba activate lerobot-Jeff
```

Conda can be used instead:

```bash
bash ./setup_env.sh --conda lerobot-Jeff
conda activate lerobot-Jeff
```

Install `lerobot-Jeff`, the reBot SDK, and the PICO Python SDK into the active environment:

```bash
bash ./setup_env.sh --install
```

Verify the installation:

```bash
python -c 'import lerobot, motorbridge, pinocchio, reBotArm_control_py, xensevr_pc_service_sdk; print("lerobot-Jeff environment OK")'
```

The setup script installs the checkout in editable mode. Source changes in this repository are therefore used without reinstalling the package.

## PICO 4 SDK

The PICO integration has two layers:

1. `xensevr_pc_service_sdk` is the Python binding that receives headset and controller data from the PICO PC bridge service.
2. `src/lerobot/teleoperators/pico4/` converts that raw device data into LeRobot Cartesian actions.

The default configuration uses the right controller. On connection, the SDK checks that non-zero controller pose data is available. Each control cycle reads the controller pose, grip value, trigger value, and physical buttons.

The `Pico4` teleoperator then:

- Filters tracking jumps and optionally smooths raw poses.
- Converts the PICO controller frame into the robot world frame.
- Uses relative controller translation from the moment the grip is pressed.
- Aligns controller orientation with the robot orientation at each grip engagement.
- Limits output position and rotation velocity.
- Emits the ten-field TCP and gripper action expected by `rebot_rs_follower`.

Default controller mapping:

| Input | Behavior |
| --- | --- |
| Right grip | Hold to enable TCP motion; release to freeze the current target pose. |
| Right trigger | Controls the gripper; released is open and fully pressed is closed. |
| A button | Returns reBot to the configured start pose and synchronizes the PICO target again. |
| Controller position | Controls relative TCP translation while grip is held. |
| Controller orientation | Controls TCP orientation while grip is held. |

Useful PICO CLI options:

| Option | Default | Description |
| --- | ---: | --- |
| `--teleop.use_right_controller=true` | `true` | Use the right controller. |
| `--teleop.use_left_controller=true --teleop.use_right_controller=false` | `false / true` | Use the left controller instead of the default right controller. |
| `--teleop.pos_sensitivity=1.0` | `1.0` | Scale controller translation. |
| `--teleop.ori_sensitivity=1.0` | `1.0` | Scale controller rotation. |
| `--teleop.filter_window_size=1` | `1` | Moving-average filter window. |
| `--teleop.position_jump_threshold=0.1` | `0.1 m` | Reject larger single-frame tracking jumps. |
| `--teleop.max_pos_velocity=2.0` | `2.0 m/s` | Limit output translation velocity. |
| `--teleop.max_rot_velocity=6.28` | `6.28 rad/s` | Limit output angular velocity. |

The PICO coordinate origin is established when the headset tracking application starts. Restarting that application creates a new origin. The robot target is synchronized from the arm's current TCP pose when teleoperation starts and whenever the A-button start action completes.

## reBot SDK

The reBot integration also has two layers:

1. `reBotArm_control_py` provides actuator groups, RobStride motor communication, robot model loading, forward kinematics, and inverse kinematics.
2. `src/lerobot/robots/rebot_rs_follower/` adapts that SDK to the LeRobot `Robot` interface.

When `rebot_rs_follower` connects, it loads the hardware configuration and robot model, connects the arm and gripper groups, selects the configured control mode, enables the drives, primes joint feedback, and starts the SDK control loop.

During teleoperation, the adapter:

- Converts the PICO 6D rotation action into a rotation matrix.
- Builds an absolute Cartesian target for the end effector.
- Solves only the newest pending target in a dedicated asynchronous IK worker, preventing old hand poses from queuing up.
- Holds the previous valid joint target if IK fails.
- Smooths successful joint targets before sending them to the high-rate motor loop.
- Maps normalized `gripper.pos` into the configured gripper joint range.
- Reads cached joint feedback and optional camera frames without blocking the action loop.

Important reBot options:

| Option | Default | Description |
| --- | --- | --- |
| `--robot.sdk_path=...` | auto-detect | Explicit path to the bundled reBot SDK. |
| `--robot.hw_yaml=...` | SDK default | Hardware YAML used by the actuator layer. |
| `--robot.arm_control_mode=mit` | `mit` | Arm mode; MIT is the default, with explicit `posvel`/`pos_vel` compatibility. |
| `--robot.gravity_compensation_enabled=true` | `true` | Enable Pinocchio gravity feed-forward in MIT mode. |
| `--robot.gravity_compensation_scale=1.0` | `1.0` | Gravity torque multiplier; start with `0.5` during initial tuning. |
| `--robot.joint_target_interpolation_time_s=0.03` | `0.03 s` | Joint-target smoothing time constant. |
| `--robot.feedback_max_age_s=0.5` | `0.5 s` | Threshold for stale cached feedback warnings. |
| `--robot.start_position='[...]'` | project default | Six arm joints plus gripper used at teleoperation start and by the A button. |
| `--robot.home_position='[...]'` | all zeros | Six arm joints plus gripper used during normal shutdown. |

The default reBot RS hardware configuration uses `can0`, six RobStride arm motors, and one RobStride gripper motor.

## PICO 4 + reBot Control Chain

The complete runtime sequence is:

1. The PICO tracking application defines the VR origin and streams controller state to the PC bridge service.
2. `xensevr_pc_service_sdk` exposes the latest pose and button values to Python.
3. `Pico4.get_action()` applies filtering, coordinate conversion, grip gating, relative translation, and orientation alignment.
4. The LeRobot processor pipeline validates and forwards the TCP action.
5. `RebotRSFollower.send_action()` replaces the pending IK request with the newest target.
6. The asynchronous worker solves the Cartesian target and updates the newest joint goal.
7. The reBot control loop smooths and sends arm and gripper commands through CAN.
8. On `Ctrl+C`, the arm returns to the configured mechanical home pose before the drives disconnect.

This latest-target design is intentional: if IK takes longer than one PICO frame, stale targets are discarded instead of being replayed later.

## Start PICO 4 + reBot

### 1. Activate the environment

```bash
cd lerobot-Jeff
mamba activate lerobot-Jeff
```

### 2. Bring up CAN

The bundled reBot RS configuration uses `can0` at 1 Mbps:

```bash
./can_up.sh can0 1000000
ip -details link show can0
```

### 3. Prepare PICO 4

1. Power on the headset and both controllers.
2. Start the PICO tracking client on the headset.
3. Start the PICO PC bridge service.
4. Confirm that the headset and PC are connected and controller tracking is active.
5. Place the controller in a comfortable neutral orientation before starting the robot command.

### 4. Start teleoperation

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30
```

Startup behavior for this exact robot/teleoperator pair is:

1. Connect PICO first, so missing controller data is detected before the robot is powered.
2. Connect and enable the reBot arm.
3. Move the arm to mechanical home.
4. Move the arm to the configured start pose.
5. Synchronize the PICO target with the current robot TCP pose.
6. Enter the 30 Hz teleoperation loop.

If the default cameras are not connected, disable them explicitly:

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --robot.head_camera=null \
  --robot.wrist_camera=null \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30
```

For a slower first test:

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --robot.head_camera=null \
  --robot.wrist_camera=null \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --teleop.pos_sensitivity=0.3 \
  --teleop.ori_sensitivity=0.3 \
  --fps=30
```

Preview actions without sending teleoperation targets to the robot:

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --robot.head_camera=null \
  --robot.wrist_camera=null \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30 \
  --dryrun=true
```

Remember that this preview still connects both devices and may enable the robot drives.

### 5. Record a dataset with PICO 4

`pico4` and `rebot_rs_follower` are integrated with `lerobot-record`, using the same
safe homing, start-pose, TCP synchronization, and shutdown sequence described above:

```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --dataset.repo_id=${HF_USER}/rebot-rs-pico4-demo \
  --dataset.single_task="Pick up the object" \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=60 \
  --dataset.reset_time_s=20 \
  --dataset.fps=30 \
  --dataset.push_to_hub=false
```

During recording, press the A button on the right controller to return the arm to the
recording start pose and re-sync the PICO target. If the default cameras are not
connected, also add `--robot.head_camera=null --robot.wrist_camera=null`.

## Troubleshooting

### PICO reports all-zero controller data

- Confirm that the PICO PC bridge service is running.
- Restart the tracking client on the headset.
- Confirm that the selected controller is powered, paired, and actively tracked.
- Restart the teleoperation command after valid tracking appears.

### `xensevr_pc_service_sdk` cannot be imported

Activate the intended environment and rerun:

```bash
bash ./setup_env.sh --install
```

### CAN interface is missing or down

```bash
ip link show can0
./can_up.sh can0 1000000
```

Also verify the USB-CAN adapter, Linux driver, cable, termination resistance, and the channel configured by the reBot hardware YAML.

### A camera cannot be opened

Check the available devices:

```bash
ls -l /dev/video*
```

Then change the camera paths in the robot configuration or launch with `--robot.head_camera=null --robot.wrist_camera=null`.

### IK warnings or unexpected holds

- Press A to return to the configured start pose and resynchronize the PICO target.
- Reduce `pos_sensitivity` and `ori_sensitivity`.
- Keep targets inside the reachable workspace and avoid abrupt wrist rotations.
- Verify the robot model, end-effector frame, joint feedback, and hardware zero positions.

## Publish as `lerobot-Jeff`

Create an empty GitHub repository named `lerobot-Jeff`, then point this checkout to it:

```bash
git remote set-url origin git@github.com:YOUR_GITHUB_USER/lerobot-Jeff.git
git push -u origin YOUR_BRANCH
```

Do not rename the `src/lerobot` Python package or the `lerobot-*` CLI commands when renaming the GitHub repository.
