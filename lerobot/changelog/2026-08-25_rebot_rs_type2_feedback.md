# reBot RS MIT 反馈切换为 MotorBridge Type-2 RX cache

日期：2026-08-25

## 摘要

reBot RS follower 的 MIT 运行路径从周期性同步读取 RobStride `mechPos` 参数（`0x7019`），调整为直接读取 MIT 响应持续更新的 MotorBridge Type-2/RX state cache。

本次修改分为两个阶段：

1. 先增加一个默认关闭的低频诊断，比较单个关节的 `motor.get_state()` position 与同步 `0x7019 mechPos`，验证两条反馈路径的角度定义是否一致。
2. 根据 J1 实机验证结果，在 MIT 模式关闭周期性 `0x7019` feedback sweep，并让非同步位置、速度读取优先使用 Type-2 RX cache。启动、回零、settle check 和显式诊断仍可执行同步硬件读取。

POS_VEL 兼容路径没有改为 Type-2，仍保留原有 feedback sweep。

## 原始问题

旧 MIT 路径虽然以较高频率发送控制指令，但关节位置 cache 由后台线程通过 `0x7019` 逐关节同步查询刷新。一次完整反馈 sweep 需要顺序查询机械臂和夹爪中的多个电机，因此会长期占用 CAN 参数查询通道。

实机日志中完整 sweep 通常约为 `58 ms`，与单关节 `0x7019` 查询通常约 `8 ms`、多个关节顺序读取的开销相符。这条低频、阻塞式反馈路径会与 MIT 控制帧竞争，并可能使位置观测表现为低频台阶，而不是跟随 MIT 响应持续更新。

与此同时，MotorBridge 已经把 RobStride MIT Type-2 响应解码并保存在每个电机的 latest-state cache 中，但旧的 `JointGroup.get_positions(request_feedback=False)` 没有使用这条数据路径。

## 根因与验证依据

旧数据流：

```text
MIT command loop
    ├── send_mit(...)
    └── independent feedback thread
            └── joint1..jointN sequential 0x7019 queries
                    └── JointGroup position cache
```

MotorBridge 同时存在但未用于位置观测的数据流：

```text
MIT command
    └── RobStride Type-2 response
            └── MotorBridge RX worker
                    └── motor.get_state() latest-state cache
```

为避免直接假定两种角度天然一致，先对 J1 进行了低频实机比较。采集到的 35 个样本结果为：

| 指标 | 结果 |
| --- | ---: |
| 平均绝对差值 | 约 `0.000195 rad` |
| 最大绝对差值 | `0.001749 rad`，约 `0.10°` |
| 超过 `0.0005 rad` 的样本 | 1 / 35 |
| 单次 `0x7019` 查询平均耗时 | 约 `21.5 ms` |
| 单次查询常见耗时 | 约 `8.1–8.8 ms` |
| 单次查询最大耗时 | `102.3 ms` |

J1 样本没有出现持续固定 offset、方向相反或约 `2π` 的跳变。运动中的一次较大差值可由两条数据并非在完全相同时间采样解释；当前证据支持 J1 的 Type-2 position 与 `mechPos` 使用相同单位和方向。

## 修改后的数据流

```text
MIT command
    └── Type-2 response
            └── MotorBridge RX cache
                    ├── get_positions(request_feedback=False)
                    └── get_velocities(request_feedback=False)

Explicit startup / homing / settle / diagnostic
    └── synchronous 0x7019 mechPos query
```

MIT follower 启动控制循环时传入 `feedback_sweep=False`，因此正常运行不再启动周期性 `0x7019` sweep。POS_VEL 模式仍传入 `feedback_sweep=True`。

## 详细实现

### 1. follower 配置

[config_rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py#L72) 新增以下 opt-in 诊断参数：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `position_compare_enabled` | `false` | 是否启动 Type-2 与 `mechPos` 对比线程 |
| `position_compare_motor_name` | `joint1` | 每次只比较一个指定关节 |
| `position_compare_interval_s` | `1.0` | 比较周期，单位秒 |
| `position_compare_timeout_ms` | `100` | 单次 `0x7019` 查询超时 |

配置初始化会验证电机名非空、比较周期为有限正数、查询超时为正数。连接硬件后还会确认目标电机属于 arm group。

### 2. reBot RS follower 生命周期

[rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py#L276) 在 MIT 模式启动控制循环时关闭周期性 feedback sweep；POS_VEL 路径继续启用旧 sweep。

[rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py#L296) 增加独立的低频诊断线程：

- 每个周期只比较一个关节；
- 输出完整 MotorBridge state、Type-2 position、`mechPos`、差值和查询耗时；
- 查询异常只记录日志，不终止 MIT 控制循环；
- `disconnect()` 会先设置 stop event，并等待诊断线程退出，避免释放 CAN/电机对象后线程继续访问硬件。

诊断没有放进 500 Hz MIT callback，避免同步参数查询直接阻塞高频控制线程。

### 3. reBotArm SDK 反馈读取

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L454) 增加跨 MotorBridge binding 表现形式的 state 字段读取，兼容对象或字典，以及 `pos`/`position`、`vel`/`velocity` 字段名。

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L477) 增加 MIT/RobStride Type-2 position cache 读取：

- 仅在整个 group 为 RobStride 且当前模式为 MIT 时启用；
- 任一 state 缺失、字段不是实数或数值非有限时不使用不完整结果；
- 完整有效时原子更新 group position cache 及时间戳；
- 该路径不执行 CAN 参数查询。

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L598) 调整 `get_positions()`：

- MIT/RobStride 且 `request_feedback=False`：读取 Type-2 RX cache；
- `request_feedback=True`：继续执行同步 `0x7019` sweep；
- 其他模式：继续使用原有 group cache。

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L681) 同样让 MIT 非同步速度读取使用 Type-2 state，不改用 RobStride `0x701A mechVel`，因为该参数此前实测的比例和符号与 `dq/dt` 不一致。

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L624) 增加单关节 Type-2/`mechPos` 比较接口。同步查询使用共享 feedback I/O lock，避免与其他同步反馈事务并发访问 CAN。

[rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py#L1026) 为 `start_control_loop()` 增加 `feedback_sweep` 参数，默认值为 `true`，保持现有 SDK 调用者兼容。只有 reBot RS follower 的 MIT 路径显式关闭它。

### 4. 测试覆盖

[test_rebotarm_feedback_cache.py](../../tests/robots/test_rebotarm_feedback_cache.py#L57) 增加或保留了以下针对性检查：

- MIT position 读取使用 Type-2 cache，且不调用 `robstride_get_param_f32()`；
- MIT velocity 读取不发送额外 feedback request；
- 单关节对比正确返回 Type-2 position、`mechPos`、差值和查询参数；
- 控制循环可通过 `feedback_sweep=False` 跳过后台 sweep；
- 同步 sweep 失败时保留上一次有效 cache 和时间戳；
- 非有限同步反馈不会覆盖有效 cache。

## 使用方式

诊断默认关闭。使用 PICO 4 对 J1 进行比较时：

```bash
uv run lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --robot.position_compare_enabled=true \
  --robot.position_compare_motor_name=joint1 \
  --robot.position_compare_interval_s=1.0 \
  --robot.position_compare_timeout_ms=100 \
  --fps=30
```

没有连接默认相机时，额外传入：

```bash
--robot.head_camera=null \
--robot.wrist_camera=null
```

典型日志：

```text
[POS_COMPARE] joint1 state=MotorState(...) type2=+0.023010 rad mechPos=+0.022839 rad diff=+0.000170 rad query=8.1 ms
```

## 并发、生命周期和安全考虑

- 正常 MIT cache 读取只访问 MotorBridge latest state，不持有 feedback I/O lock，也不增加同步 CAN 事务。
- 显式 `0x7019` 查询仍使用 feedback I/O lock 串行化。
- 诊断线程为 daemon，但仍在 follower 断开前显式停止和 join。
- 未知 state 格式、state 缺失和查询异常会记录告警，不会替换为非有限位置，也不会中断控制线程。
- `start_control_loop(feedback_sweep=True)` 的默认行为未改变，避免影响其他机器人和 SDK 用户。
- POS_VEL 反馈语义尚未单独验证，因此没有关闭其周期性 sweep。
- 这是一项控制软件反馈路径调整，不构成功能安全认证；机械限位、急停和现场风险控制仍需由系统其他层保证。

## 验证状态

### 已完成

- J1 实机 Type-2 与 `0x7019 mechPos` 对比，共 35 个样本。
- 对比运行期间 Pico4、两路相机和 reBot RS 正常连接。
- 30 Hz 遥操作运行 681 ticks，有效 cadence 为 `29.88 Hz`；日志中 CAN send error 为 0。
- Ctrl-C 后正常执行机械回零并依次断开 Pico4、相机和机器人。
- 当前相关 Python 文件通过 `compileall` 语法编译检查。
- `git diff --check` 对主仓库相关文件未发现空白错误。

### 未完成或受限

- 当前 `.venv` 未安装 `pytest`，执行
  `uv run python -m pytest tests/robots/test_rebotarm_feedback_cache.py tests/robots/test_rebot_rs_follower.py -q`
  失败，错误为 `No module named pytest`。测试代码已添加，但本环境尚未实际运行该 pytest 集合。
- 现有实机对比只覆盖 J1，位置范围约 `0.018–0.030 rad`。
- 尚未分别验证 J2～J6，也未覆盖大角度或跨 `±π` 的 wrap 行为。
- 上述实机日志是在 legacy sweep 仍运行、用于验证两种位置来源一致性的阶段采集；最终“MIT 关闭 sweep、全部关节使用 Type-2 cache”的版本仍需再次进行完整硬件回归。

因此，目前可以确认 J1 的两条位置反馈在已测试范围内一致，也可以确认最终代码的数据流已经完成切换；尚不能仅凭该批数据宣称所有关节和全量程都已完成验证。

## 后续建议

1. 分别将 `position_compare_motor_name` 设置为 `joint2` 到 `joint6`，在多个安全姿态采样。
2. 对可能接近 `±π` 的关节检查 Type-2 是否 wrap；若存在 wrap，应在写入 group cache 前增加连续角度展开。
3. 在 MIT feedback sweep 已关闭的最终代码上重复遥操作、启动、回零和 Ctrl-C 流程，确认 cache age、重力补偿、FK 和 settle 行为。
4. 安装 test extra 后运行相关 pytest，并在有条件时执行完整机器人测试集。
5. 验证稳定后再决定是否保留诊断配置，或把它降级为专用维护工具。

## 相关文件

- [src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
- [src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py)
- [tests/robots/test_rebotarm_feedback_cache.py](../../tests/robots/test_rebotarm_feedback_cache.py)
- [tests/robots/test_rebot_rs_follower.py](../../tests/robots/test_rebot_rs_follower.py)
