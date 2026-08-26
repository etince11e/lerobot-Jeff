# reBot RS Cartesian 数据集格式统一

日期：2026-08-26

## 摘要

本次变更将 `rebot_rs_follower` 新录制数据中的 `action` 与
`observation.state` 统一为相同顺序的十维 Cartesian 表示：

```text
tcp.x, tcp.y, tcp.z,
tcp.r1, tcp.r2, tcp.r3, tcp.r4, tcp.r5, tcp.r6,
gripper.pos
```

TCP 旋转使用连续 6D rotation representation，夹爪命令与反馈均以
`[0, 1]` 范围写入数据集。相机画面仍作为独立的
`observation.images.*` feature 保存。

## 原始问题

此前 action 已经采用十维 TCP 控制格式，但 observation 保存的是：

- `joint1.pos` 到 `joint6.pos`；
- 物理量纲的 `gripper.pos`；
- 只有 `tcp.x/y/z`，没有 TCP 方向。

因此 action 与 observation 的状态空间不一致，使用 Cartesian policy
训练时还需要额外转换；夹爪 action 是归一化值，而 observation 夹爪是物理关节位置，
两侧语义也不一致。

此外，录制循环虽然接收了 `robot.send_action()` 返回的实际 action，写盘时却仍使用
teleoperator processor 的 action。这会使机器人端裁剪或修正后的值无法反映到数据集。

## 根因

数据集 schema 来自机器人的 `action_features` 和 `observation_features`，随后由
`lerobot-record` 生成 metadata。`DatasetWriter` 只校验并写入既有 schema，不能决定
机器人状态使用 joint 还是 Cartesian 表示。

具体表现为：

- [`rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
  的 observation feature 仍声明为关节位置、物理夹爪值和 TCP 位置；
- `_collect_observation()` 已经执行 FK，但此前只取 FK 的平移部分；
- [`lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py)
  写入 action frame 时没有使用 `send_action()` 的返回结果。

## 修改动机与设计

Pico4 当前输出的控制格式已经是：

```text
tcp.x/y/z + tcp.r1-r6 + gripper.pos
```

因此让机器人 observation 使用同一表示，可以保证：

1. action 与 observation.state 均为十维且字段顺序一致；
2. TCP 姿态不需要在训练前从关节角重新计算；
3. 夹爪 action 与 observation 都使用 `[0, 1]`；
4. 数据集保存的是机器人实际接受的 action，而不是未经机器人端处理的输入。

本次变更没有修改 IK、MIT 控制、关节插值、重力补偿、CAN 通信或相机采集逻辑。

## 修改后的数据流

```text
Pico4 十维 TCP action
    ↓
robot.send_action()
    ├─ gripper.pos 裁剪到 [0, 1]
    ├─ TCP 目标进入异步 IK
    └─ 返回规范化后的十维 action
             ↓
       数据集 action

机械臂关节反馈
    ↓
正向运动学 FK
    ├─ tcp.x/y/z
    ├─ rotation matrix 前两列 → tcp.r1-r6
    └─ 物理夹爪位置 → [0, 1]
             ↓
    数据集 observation.state
```

## 具体实现

### 1. 统一 action 和 observation feature

在 [`src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
中，以 `TCP_ACTION_KEYS` 作为 action 和 observation 的共同字段来源。

新创建数据集的 schema 为：

```text
action:
  dtype: float32
  shape: (10,)
  names: [tcp.x, tcp.y, tcp.z, tcp.r1, tcp.r2, tcp.r3,
          tcp.r4, tcp.r5, tcp.r6, gripper.pos]

observation.state:
  dtype: float32
  shape: (10,)
  names: [tcp.x, tcp.y, tcp.z, tcp.r1, tcp.r2, tcp.r3,
          tcp.r4, tcp.r5, tcp.r6, gripper.pos]
```

关节反馈仍在机器人内部用于 FK、控制误差诊断和安全控制，但不再作为该机器人默认的
dataset state feature 写盘。

### 2. 从 FK 生成 TCP 6D rotation

`_collect_observation()` 现在读取 FK 返回的 4×4 TCP transform，并按如下顺序展开
旋转矩阵的前两列：

```text
R00, R10, R20, R01, R11, R21
```

结果对应 `tcp.r1` 到 `tcp.r6`，与 Pico4 action 所使用的 6D rotation convention 一致。

### 3. 归一化 observation 夹爪值

新增 `_normalize_gripper_position()`，使用机器人配置中的：

```text
gripper_closed_pos
gripper_open_pos
```

执行线性映射：

```text
(position - closed) / (open - closed)
```

结果裁剪到 `[0, 1]`。按照当前默认配置，`0` 表示闭合位置，`1` 表示打开位置。

### 4. 规范化 action 夹爪值

`send_action()` 现在先构造固定字段顺序的 canonical action，并将
`gripper.pos` 裁剪到 `[0, 1]`。该值一方面被映射到物理夹爪目标，另一方面作为函数返回值
供 recorder 写盘。

### 5. 保存机器人实际接受的 action

在 [`src/lerobot/scripts/lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py)
中，action frame 改为使用 `robot.send_action()` 返回的 action。这使夹爪裁剪以及其他
机器人端可能执行的 action 修正能够进入最终数据集。

### 6. 测试更新

在 [`tests/robots/test_rebot_rs_follower.py`](../../tests/robots/test_rebot_rs_follower.py)
中补充并更新了以下验证：

- action 与 observation 的非图像 feature 顺序均等于 `TCP_ACTION_KEYS`；
- observation 不再包含 `joint*.pos`；
- identity rotation 被转换为预期的 6D 表示；
- 物理夹爪中点被归一化为 `0.5`；
- 超出范围的 action 夹爪值在控制和返回前被裁剪为 `1.0`。

## 兼容性与注意事项

- 已有数据集的 metadata 不会自动迁移。旧数据集包含不同的 observation schema，不能直接
  使用 `--resume=true` 追加新格式数据；应使用新的 `repo_id` 或新的空目录录制。
- replay 和 policy 配置必须与十维 action schema 匹配。
- 相机 feature 没有变化，仍然独立于十维 `observation.state`。
- `get_current_tcp_pose_quat()` 仍保留原有物理夹爪值语义，用于 Pico4 初始位姿同步；只有
  写入 dataset observation 的夹爪反馈会归一化。
- `gripper_open_pos` 与 `gripper_closed_pos` 必须不同，否则归一化无法定义。

## 验证

已完成：

```text
tests/robots/test_rebot_rs_follower.py    11 passed
ruff check                               passed
ruff format --check                      passed
git diff --check                         passed
```

同时通过实际 feature 聚合代码验证，新 schema 为：

```text
action             float32 (10,) TCP_ACTION_KEYS
observation.state  float32 (10,) TCP_ACTION_KEYS
```

未完成：

- `tests/test_control_robot.py` 在当前环境被跳过，因为缺少可选依赖
  `deepdiff`（测试提示：`install lerobot[hardware]`）；
- 本轮未连接真实 reBot RS、Pico4、CAN 适配器或相机执行硬件录制验证。

## 后续工作

- 如需同时支持 joint 与 Cartesian 两种录制 schema，建议增加独立的 recording mode，
  不要改变机器人实际接收的 TCP 控制接口；
- 可以为录制链路增加无硬件集成测试，验证 `send_action()` 返回的裁剪值确实进入
  `dataset.add_frame()`；
- 如果需要迁移旧数据，可单独提供 dataset conversion 工具，重新计算 TCP 6D rotation
  和归一化夹爪列。

## 相关文件

- [`src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [`src/lerobot/scripts/lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py)
- [`tests/robots/test_rebot_rs_follower.py`](../../tests/robots/test_rebot_rs_follower.py)
