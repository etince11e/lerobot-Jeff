# reBot RS + Pico4 Environment Setup / 环境安装

## 中文

这是给 `rebot_rs_follower` + `pico4` 遥操作单独准备的环境安装流程。

### 依赖

- Ubuntu + Python 3.12
- 当前这个 `lerobot` 仓库
- `third_party/reBotArm_control_py`
- `third_party/XenseVR-PC-Service`

### 安装

```bash
cd /home/jeff/lerobot-rebot/lerobot
bash ./setup_env.sh --mamba lerobot-rebot
mamba activate lerobot-rebot
bash ./setup_env.sh --install
```

### 验证

```bash
python -c 'import lerobot, motorbridge, pinocchio, reBotArm_control_py, xensevr_pc_service_sdk; print("ok")'
```

### 启动

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30
```

### Dry run

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30 \
  --dryrun=true
```

### 说明

- 安装脚本会自动构建并挂载 XenseVR PC Service SDK。
- 如果你的 XenseVR SDK 不在默认位置，可以设置 `XENSE_VENDOR_ROOT`。
- 脚本按仓库根目录解析相对路径，整个项目换位置通常不会冲突。

## English

This is a dedicated setup flow for `rebot_rs_follower` + `pico4` teleoperation.

### Requirements

- Ubuntu + Python 3.12
- this `lerobot` checkout
- `third_party/reBotArm_control_py`
- `third_party/XenseVR-PC-Service`

### Install

```bash
cd /home/jeff/lerobot-rebot/lerobot
bash ./setup_env.sh --mamba lerobot-rebot
mamba activate lerobot-rebot
bash ./setup_env.sh --install
```

### Verify

```bash
python -c 'import lerobot, motorbridge, pinocchio, reBotArm_control_py, xensevr_pc_service_sdk; print("ok")'
```

### Teleoperate

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30
```

### Dry run

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --fps=30 \
  --dryrun=true
```

### Notes

- The installer builds and stages the XenseVR PC Service SDK automatically.
- If your XenseVR SDK lives elsewhere, set `XENSE_VENDOR_ROOT`.
- Paths are resolved from the repo root, so moving the whole project usually does not break them.
