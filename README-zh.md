# lerobot-Jeff

中文 | [English](README.md)

`lerobot-Jeff` 是一个真实机器人遥操作项目，通过 LeRobot 控制链路将 PICO 4 VR 手柄连接到 reBot RS 从动机械臂。项目包含环境安装、PICO 4 输入处理、reBot SDK 集成、笛卡尔目标到关节目标的逆运动学、CAN 电机控制、可选相机，以及安全的启动和退出处理。

仓库名称为 `lerobot-Jeff`。Python 包名和命令行工具仍然保留为 `lerobot`，因此 `import lerobot` 等导入方式和 `lerobot-teleoperate` 等命令无需修改。

## 安全须知

真实机器人命令会给 reBot 驱动器上电，并自动移动机械臂。每次运行前请完成以下检查：

- 清空机械臂工作空间，并确保急停开关触手可及。
- 检查 CAN 通道、关节方向、零位、起始位和机械零位。
- 在机械臂到达配置的起始位之前，不要按住 PICO 抓握键。
- 新设备首次测试时，降低 PICO 的位置和姿态灵敏度。
- 使用 `Ctrl+C` 正常退出，并等待机械臂回到机械零位后再断电。

`--dryrun=true` 是动作预览模式，不是无硬件仿真。它仍会连接 PICO 设备和 reBot 机械臂，也可能使能驱动器，但不会发送生成的遥操作动作。

## 系统概览

```mermaid
flowchart LR
    A[PICO 4 头显与手柄] --> B[PICO PC 桥接服务]
    B --> C[PICO Python SDK]
    C --> D[LeRobot Pico4 遥操作器]
    D -->|TCP 位姿与夹爪动作| E[LeRobot 动作处理链]
    E --> F[reBot RS 从动机械臂]
    F --> G[仅保留最新目标的异步 IK]
    G --> H[reBot 控制 SDK]
    H --> I[CAN 总线]
    I --> J[机械臂与夹爪电机]
```

PICO 和 reBot 之间共享的控制动作包含：

- `tcp.x`、`tcp.y`、`tcp.z`：单位为米的末端绝对位置。
- `tcp.r1` 到 `tcp.r6`：连续的末端 6D 旋转表示。
- `gripper.pos`：范围为 `[0, 1]` 的归一化夹爪指令。

## 环境要求

- Ubuntu 22.04 或更高版本。
- Python 3.12。
- Conda 或 Mamba，推荐使用 Miniforge。
- PICO 4 头显、已配对手柄，以及安装在头显中的 PICO 追踪客户端。
- 能够接收手柄追踪数据且正在运行的 PICO PC 桥接服务。
- reBot RS 机械臂、USB-CAN 适配器，以及已配置的 SocketCAN 接口。
- 本项目所需的 reBot 与 PICO SDK 文件已经放在仓库约定的 `third_party/` 位置。
- 可选的头部相机和腕部相机。默认设备分别为 `/dev/video5` 和 `/dev/video3`。

安装基础系统工具：

```bash
sudo apt update
sudo apt install -y build-essential git git-lfs iproute2 can-utils
```

## 环境安装

克隆项目并初始化两个 SDK submodule：

```bash
git clone --recurse-submodules https://github.com/YOUR_GITHUB_USER/lerobot-Jeff.git
cd lerobot-Jeff
git lfs install
git lfs pull
```

本仓库将 reBot 和 XenseVR SDK 源码作为 Git submodule 管理：

- `third_party/reBotArm_control_py`：reBot 机械臂 SDK。
- `third_party/XenseVR-PC-Service`：XenseVR PC 服务及原生 SDK。

如果克隆时没有使用 `--recurse-submodules`，请在运行安装脚本前初始化 SDK 目录：

```bash
git submodule update --init --recursive
```

可以使用以下命令确认两个 submodule 已经检出：

```bash
git submodule status
```

使用 Mamba 创建 Python 3.12 环境：

```bash
bash ./setup_env.sh --mamba lerobot-Jeff
mamba activate lerobot-Jeff
```

也可以使用 Conda：

```bash
bash ./setup_env.sh --conda lerobot-Jeff
conda activate lerobot-Jeff
```

在已激活环境中安装 `lerobot-Jeff`、reBot SDK 和 PICO Python SDK：

```bash
bash ./setup_env.sh --install
```

验证安装：

```bash
python -c 'import lerobot; print("lerobot OK")'
python -c 'import motorbridge; print("motorbridge OK")'
python -c 'import pinocchio ; print("pinocchio OK")'
python -c 'import reBotArm_control_py; print("reBotArm_control_py OK")'
python -c 'import xensevr_pc_service_sdk; print("xense_vr_sdk OK")'

```

安装脚本会以 editable 模式安装当前项目，因此修改本仓库源码后不需要重新安装 Python 包。

## PICO 4 SDK

PICO 集成分为两层：

1. `xensevr_pc_service_sdk` 是从 PICO PC 桥接服务接收头显和手柄数据的 Python 绑定。
2. `src/lerobot/teleoperators/pico4/` 将原始设备数据转换为 LeRobot 笛卡尔动作。

默认配置使用右手柄。连接时，SDK 会检查是否能够获取非零的手柄位姿数据。每个控制周期会读取手柄位姿、抓握值、扳机值和实体按键。

`Pico4` 遥操作器随后会：

- 过滤追踪跳变，并可选择对原始位姿进行平滑。
- 将 PICO 手柄坐标系转换为机器人世界坐标系。
- 从按下抓握键的时刻开始计算手柄相对位移。
- 每次启用抓握控制时，将手柄姿态与机器人当前姿态对齐。
- 限制输出的位置速度和旋转速度。
- 输出 `rebot_rs_follower` 所需的十维 TCP 与夹爪动作。

默认手柄映射：

| 输入         | 行为                                              |
| ------------ | ------------------------------------------------- |
| 右手柄抓握键 | 按住时允许 TCP 运动；松开后保持当前目标位姿。     |
| 右手柄扳机键 | 控制夹爪；松开为打开，完全按下为闭合。            |
| A 键         | 让 reBot 返回配置的起始位，并重新同步 PICO 目标。 |
| 手柄位置     | 抓握键按住时控制 TCP 相对平移。                   |
| 手柄姿态     | 抓握键按住时控制 TCP 姿态。                       |

常用 PICO 命令行参数：

| 参数                                                                    |         默认值 | 说明                             |
| ----------------------------------------------------------------------- | -------------: | -------------------------------- |
| `--teleop.use_right_controller=true`                                    |         `true` | 使用右手柄。                     |
| `--teleop.use_left_controller=true --teleop.use_right_controller=false` | `false / true` | 改用左手柄，并关闭默认的右手柄。 |
| `--teleop.pos_sensitivity=1.0`                                          |          `1.0` | 缩放手柄平移量。                 |
| `--teleop.ori_sensitivity=1.0`                                          |          `1.0` | 缩放手柄旋转量。                 |
| `--teleop.filter_window_size=1`                                         |            `1` | 移动平均滤波窗口。               |
| `--teleop.position_jump_threshold=0.1`                                  |        `0.1 m` | 拒绝超过阈值的单帧追踪跳变。     |
| `--teleop.max_pos_velocity=2.0`                                         |      `2.0 m/s` | 限制输出平移速度。               |
| `--teleop.max_rot_velocity=6.28`                                        |   `6.28 rad/s` | 限制输出角速度。                 |

PICO 坐标原点在头显追踪应用启动时建立。重启该应用会产生新的坐标原点。遥操作启动时，以及 A 键回到起始位完成后，机器人目标都会根据机械臂当前 TCP 位姿重新同步。

## reBot SDK

reBot 集成同样分为两层：

1. `reBotArm_control_py` 提供执行器分组、RobStride 电机通信、机器人模型加载、正运动学和逆运动学。
2. `src/lerobot/robots/rebot_rs_follower/` 将该 SDK 适配到 LeRobot 的 `Robot` 接口。

`rebot_rs_follower` 连接时会加载硬件配置和机器人模型，连接机械臂与夹爪分组，选择配置的控制模式，使能驱动器，初始化关节反馈，并启动 SDK 控制循环。

遥操作过程中，该适配层会：

- 将 PICO 的 6D 旋转动作转换为旋转矩阵。
- 构造末端绝对笛卡尔目标。
- 在独立异步 IK 线程中只求解最新的待处理目标，避免旧的手部位姿排队累积。
- IK 失败时保持上一个有效关节目标。
- 对成功求解的关节目标进行平滑，再发送到高频电机循环。
- 将归一化 `gripper.pos` 映射到配置的夹爪关节范围。
- 非阻塞地读取缓存关节反馈和可选相机画面。

重要的 reBot 参数：

| 参数                                             | 默认值     | 说明                                                               |
| ------------------------------------------------ | ---------- | ------------------------------------------------------------------ |
| `--robot.sdk_path=...`                           | 自动检测   | 显式指定仓库内 reBot SDK 的路径。                                  |
| `--robot.hw_yaml=...`                            | SDK 默认值 | 执行器层使用的硬件 YAML。                                          |
| `--robot.arm_control_mode=mit`                   | `mit`      | 机械臂模式；默认使用 MIT 控制，也兼容显式指定 `posvel`/`pos_vel`。 |
| `--robot.gravity_compensation_enabled=true`      | `true`     | MIT 模式下启用 Pinocchio 重力前馈。                                |
| `--robot.gravity_compensation_scale=1.0`         | `1.0`      | 重力补偿力矩倍率；首次调试可从 `0.5` 开始。                        |
| `--robot.joint_target_interpolation_time_s=0.03` | `0.03 s`   | 关节目标平滑时间常数。                                             |
| `--robot.feedback_max_age_s=0.5`                 | `0.5 s`    | 缓存反馈过期告警阈值。                                             |
| `--robot.start_position='[...]'`                 | 项目默认值 | 遥操作启动和按下 A 键时使用的六个机械臂关节加夹爪位置。            |
| `--robot.home_position='[...]'`                  | 全零       | 正常退出时使用的六个机械臂关节加夹爪位置。                         |

默认 reBot RS 硬件配置使用 `can0`、六个 RobStride 机械臂电机和一个 RobStride 夹爪电机。

## PICO 4 + reBot 控制链路

完整运行流程如下：

1. PICO 追踪应用建立 VR 坐标原点，并将手柄状态发送到 PC 桥接服务。
2. `xensevr_pc_service_sdk` 向 Python 提供最新位姿和按键值。
3. `Pico4.get_action()` 执行滤波、坐标转换、抓握门控、相对平移和姿态对齐。
4. LeRobot 处理链校验并转发 TCP 动作。
5. `RebotRSFollower.send_action()` 使用最新目标替换尚未处理的 IK 请求。
6. 异步线程求解笛卡尔目标并更新最新关节目标。
7. reBot 控制循环平滑关节目标，并通过 CAN 发送机械臂和夹爪指令。
8. 按下 `Ctrl+C` 后，机械臂先返回配置的机械零位，再断开驱动器。

只保留最新目标是有意设计：如果一次 IK 求解时间超过一个 PICO 帧周期，过期目标会被丢弃，而不会在之后继续回放。

## 启动 PICO 4 + reBot

### 1. 激活环境

```bash
cd lerobot-Jeff
mamba activate lerobot-Jeff
```

### 2. 启动 CAN

仓库内的 reBot RS 默认配置使用 1 Mbps 的 `can0`：

```bash
./can_up.sh can0 1000000
ip -details link show can0
```

### 3. 准备 PICO 4

1. 打开头显和两个手柄。
2. 在头显中启动 PICO 追踪客户端。
3. 启动 PICO PC 桥接服务。
4. 确认头显已连接到电脑，并且手柄追踪正常。
5. 启动机器人命令前，将手柄保持在舒适的中性姿态。

### 4. 启动遥操作

```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30
```

该机器人与遥操作器组合的实际启动行为如下：

1. 先连接 PICO，在机械臂上电前检查手柄数据是否缺失。
2. 连接并使能 reBot 机械臂。
3. 将机械臂移动到机械零位。
4. 将机械臂移动到配置的起始位。
5. 使用当前机器人 TCP 位姿同步 PICO 目标。
6. 进入 30 Hz 遥操作循环。

如果没有连接默认相机，请显式禁用相机：

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

首次测试建议降低灵敏度：

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

只预览动作、不向机器人发送遥操作目标：

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

请注意，该预览模式仍会连接两个设备，并且可能使能机器人驱动器。

### 5. 使用 PICO 4 录制数据集

`pico4` 与 `rebot_rs_follower` 已集成到 `lerobot-record`，启动和退出时沿用上面的
安全回零、起始位和 TCP 位姿同步流程：

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

录制期间按右手柄 A 键可让机械臂回到录制起始位并重新同步 PICO 目标。若未连接
默认相机，请同样添加 `--robot.head_camera=null --robot.wrist_camera=null`。

## 故障排查

### PICO 手柄数据全部为零

- 确认 PICO PC 桥接服务正在运行。
- 重启头显中的追踪客户端。
- 确认所选手柄已开机、已配对并处于正常追踪状态。
- 出现有效追踪数据后，重新启动遥操作命令。

### 无法导入 `xensevr_pc_service_sdk`

激活目标环境并重新执行：

```bash
bash ./setup_env.sh --install
```

### CAN 接口不存在或未启动

```bash
ip link show can0
./can_up.sh can0 1000000
```

同时检查 USB-CAN 适配器、Linux 驱动、线缆、终端电阻，以及 reBot 硬件 YAML 中配置的通道。

### 无法打开相机

检查当前视频设备：

```bash
ls -l /dev/video*
```

然后修改机器人配置中的相机路径，或者使用 `--robot.head_camera=null --robot.wrist_camera=null` 启动。

### 出现 IK 告警或机械臂意外保持不动

- 按下 A 键返回配置的起始位，并重新同步 PICO 目标。
- 降低 `pos_sensitivity` 和 `ori_sensitivity`。
- 将目标保持在机械臂可达空间内，避免腕部突然大角度旋转。
- 检查机器人模型、末端坐标系、关节反馈和硬件零位。

## 以 `lerobot-Jeff` 名称发布

在 GitHub 创建名为 `lerobot-Jeff` 的空仓库，然后将当前工作区指向该仓库：

```bash
git remote set-url origin git@github.com:YOUR_GITHUB_USER/lerobot-Jeff.git
git push -u origin YOUR_BRANCH
```

重命名 GitHub 仓库时，不要修改 `src/lerobot` Python 包名或 `lerobot-*` 命令行工具名称。
