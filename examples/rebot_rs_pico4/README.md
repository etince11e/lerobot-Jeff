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

### Notes

- This environment is for RS teleoperation only.
- Do not mix it with the older B601 motorbridge stack in the same env.
- If you are developing the SDK from source, you can also point the robot at it
  with `--robot.sdk_path=../../third_party/reBotArm_control_py`.
- If your XenseVR SDK lives elsewhere, set
  `XENSE_VENDOR_ROOT=/path/to/XenseVR-PC-Service`.
- The script resolves paths from the current `lerobot` checkout, so moving the
  whole project folder to a new location should not introduce path conflicts.
