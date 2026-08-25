# reBot RS + Pico4

## 中文

这个示例把 `pico4` 遥操作接到 `rebot_rs_follower`，并使用
`lerobot/third_party/reBotArm_control_py` 里的 IK / 控制栈。

### 安装

要求：

- 你已经激活 `lerobot-xense` 环境，且其中的 Python 是 3.12
- 当前这份 `lerobot` 仓库
- `lerobot/third_party/reBotArm_control_py`
- `lerobot/third_party/XenseVR-PC-Service`

安装脚本会自动把 XenseVR PC Service SDK 的 `include/` 和 `lib/`
复制到 `src/lerobot/teleoperators/pico4/xensevr-pc-service-pybind/`
并安装 `xensevr_pc_service_sdk`。

```bash
source /path/to/lerobot-xense/bin/activate
cd lerobot/examples/rebot_rs_pico4
bash ./setup_env.sh --install
```

如果 `reBotArm_control_py` 不在默认位置：

```bash
REBOT_SDK_ROOT=../../third_party/reBotArm_control_py bash ./setup_env.sh --install
```

### 验证

```bash
python -c 'import lerobot, motorbridge, pinocchio, reBotArm_control_py; print("ok")'
python -c 'import xensevr_pc_service_sdk; print("ok")'
```

### 遥操作

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30
```

`rebot_rs_follower` 直接接收 Pico 的 `tcp.x/y/z`、`tcp.r1-r6` 和
`gripper.pos`。

如果只想检查配置和导入，不连接硬件：

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30 \
  --dryrun=true
```

### 录制数据集

`pico4` 和 `rebot_rs_follower` 已集成到 `lerobot-record`。录制启动时会先连接
Pico4，再连接机械臂并依次回机械零位、进入录制起始位，最后用机械臂当前 TCP
位姿初始化 Pico4 的绝对目标，避免第一帧目标跳变。

```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --dataset.repo_id=${HF_USER}/rebot-rs-pico4-demo \
  --dataset.single_task="Pick up the object" \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=60 \
  --dataset.reset_time_s=20 \
  --dataset.fps=30 \
  --dataset.push_to_hub=false
```

录制期间按 Pico4 右手柄 A 键会让机械臂回到录制起始位，并重新同步 Pico4
目标位姿。数据集 action 保存 `tcp.x/y/z`、`tcp.r1-r6` 和 `gripper.pos`；
observation 保存关节位置、夹爪位置、TCP 位置以及已配置的相机画面。程序退出时
机械臂会先安全回机械零位，再断开设备。

### 说明

- 这个环境只面向 RS 遥操作。
- 不要和旧的 B601 motorbridge 线混在同一个环境里。
- 如果你在本地改 SDK 源码，也可以直接指定：
  `--robot.sdk_path=../../third_party/reBotArm_control_py`
- 如果你把 XenseVR SDK 放在别的位置，也可以指定：
  `XENSE_VENDOR_ROOT=/path/to/XenseVR-PC-Service`
- 脚本默认会从当前 `lerobot` 仓库根目录解析路径，所以整个项目文件夹搬到新位置通常不会冲突。

## English

This example connects `pico4` teleoperation to `rebot_rs_follower` and uses the
IK / control stack from `lerobot/third_party/reBotArm_control_py`.

### Install

Requirements:

- your `lerobot-xense` environment is already activated and uses Python 3.12
- this `lerobot` checkout
- `lerobot/third_party/reBotArm_control_py`
- `lerobot/third_party/XenseVR-PC-Service`

The installer automatically copies the XenseVR PC Service SDK `include/` and
`lib/` directories into `src/lerobot/teleoperators/pico4/xensevr-pc-service-pybind/`
and installs `xensevr_pc_service_sdk`.

```bash
source /path/to/lerobot-xense/bin/activate
cd lerobot/examples/rebot_rs_pico4
bash ./setup_env.sh --install
```

If `reBotArm_control_py` lives elsewhere:

```bash
REBOT_SDK_ROOT=../../third_party/reBotArm_control_py bash ./setup_env.sh --install
```

### Verify

```bash
python -c 'import lerobot, motorbridge, pinocchio, reBotArm_control_py; print("ok")'
python -c 'import xensevr_pc_service_sdk; print("ok")'
```

### Teleoperate

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30
```

`rebot_rs_follower` accepts Pico's `tcp.x/y/z`, `tcp.r1-r6`, and `gripper.pos`
directly.

To validate configs and imports without connecting hardware:

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30 \
  --dryrun=true
```

### Record a dataset

`pico4` and `rebot_rs_follower` are integrated with `lerobot-record`. At startup,
recording connects Pico4 first, connects the arm, moves through mechanical home and
the recording start pose, then initializes Pico4's absolute target from the arm's
current TCP pose to prevent a first-frame target jump.

```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --dataset.repo_id=${HF_USER}/rebot-rs-pico4-demo \
  --dataset.single_task="Pick up the object" \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=60 \
  --dataset.reset_time_s=20 \
  --dataset.fps=30 \
  --dataset.push_to_hub=false
```

During recording, press the A button on the right Pico4 controller to return the arm
to the recording start pose and re-sync Pico4's target. Dataset actions contain
`tcp.x/y/z`, `tcp.r1-r6`, and `gripper.pos`; observations contain joint positions,
gripper position, TCP position, and frames from configured cameras. On exit, the arm
returns safely to mechanical home before devices are disconnected.

### Notes

- This environment is for RS teleoperation only.
- Do not mix it with the older B601 motorbridge stack in the same env.
- If you are developing the SDK from source, you can also point the robot at it
  with `--robot.sdk_path=../../third_party/reBotArm_control_py`.
- If your XenseVR SDK lives elsewhere, set
  `XENSE_VENDOR_ROOT=/path/to/XenseVR-PC-Service`.
- The script resolves paths from the current `lerobot` checkout, so moving the
  whole project folder to a new location should not introduce path conflicts.
