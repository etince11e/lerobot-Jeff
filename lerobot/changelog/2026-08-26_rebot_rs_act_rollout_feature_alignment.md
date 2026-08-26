# reBot RS ACT rollout 特征对齐与安全回位修复

日期：2026-08-26

## 摘要

修复 `rebot_rs_follower` 使用 ACT checkpoint 进行 `lerobot-rollout` 推理时的特征维度错误，并修复 rollout 退出阶段把关节位置字典错误发送到笛卡尔动作接口的问题。

同时补充 `lerobot-rollout` 对 `rebot_rs_follower` 的配置注册导入，使 `--robot.type=rebot_rs_follower` 能够被 rollout CLI 识别。

## 用户可见问题

在 ACT checkpoint 已成功加载、Rebot 连接成功并输入 `/start` 后，控制循环立即失败：

```text
RuntimeError: The size of tensor a (7) must match the size of tensor b (10)
```

随后退出回位又出现：

```text
Missing rebot_rs_follower action keys: ['tcp.x', 'tcp.y', ...]
```

这两个问题都不是 ACT 权重损坏，也不是相机输入维度错误。

## 根因

Object-Storage 数据集和 ACT checkpoint 的状态空间为 10 维：

```text
joint1.pos ... joint6.pos
gripper.pos
tcp.x tcp.y tcp.z
```

但 rollout 原先在 [context.py](../../src/lerobot/rollout/context.py#L366) 中只保留以 `.pos` 或 `.vel` 结尾的标量特征。Rebot 的 `tcp.x`、`tcp.y`、`tcp.z` 没有这些后缀，因此被过滤掉，ACT 实际收到的 `observation.state` 只有 7 维，而 checkpoint 的 normalizer 需要 10 维。

动作侧也使用了同样的后缀过滤。Rebot 的动作空间是笛卡尔空间：

```text
tcp.x tcp.y tcp.z tcp.r1 tcp.r2 tcp.r3 tcp.r4 tcp.r5 tcp.r6 gripper.pos
```

因此动作特征会被全部过滤，后续无法构造合法的 Rebot 动作字典。

退出阶段的通用回位逻辑则把观察到的 `.pos` 关节字典直接传给 `robot.send_action()`。该接口要求完整的 TCP 动作键，并不接受纯关节位置字典。

## 修改内容

### 1. 保留全部标量观测特征

在 [context.py](../../src/lerobot/rollout/context.py#L366) 中，策略侧观测特征改为保留所有 `float` 标量和相机特征，而不是只保留 `.pos`/`.vel` 后缀。这样 Rebot 的 TCP 状态会进入 `observation.state`，10 维状态可与 checkpoint normalizer 对齐。

### 2. 保留全部标量动作特征

在 [context.py](../../src/lerobot/rollout/context.py#L387) 中，动作侧改为保留所有标量动作特征，使 Rebot 的 10 维 TCP/夹爪动作能够映射回 `send_action()`。

### 3. 增加硬件感知的回位钩子

在 [core.py](../../src/lerobot/rollout/strategies/core.py#L172) 中，通用回位逻辑会优先检查机器人是否提供 `reset_to_initial_position()`。

`rebot_rs_follower` 已提供该接口，并将机器人返回配置中的安全 `start_position`。对于没有该钩子的其他机器人，原有通用关节插值回位逻辑保持不变。

### 4. 注册 Rebot RS rollout 类型

在 [lerobot_rollout.py](../../src/lerobot/scripts/lerobot_rollout.py#L174) 中补充 `rebot_rs_follower` 导入，使对应的 `RobotConfig` 注册在 rollout CLI 启动时生效。

## 修改后的数据流

```text
Rebot observation_features
    ├── joint*.pos
    ├── gripper.pos
    ├── tcp.x / tcp.y / tcp.z
    └── head / wrist images
            ↓
rollout feature aggregation
            ↓
observation.state: 10 dimensions
            ↓
ACT normalizer and policy inference
            ↓
10-dimensional TCP action
            ↓
rebot_rs_follower.send_action()
```

## 安全与生命周期注意事项

- `--interactive=true` 只保证在输入 `/start` 前不进入策略控制循环；连接阶段仍会初始化电机和相机。
- `reset_to_initial_position()` 当前返回的是 Rebot 配置中的 `start_position`，不是通用 rollout 捕获的原始关节字典；这是为了使用 Rebot 自己的 IK/轨迹回位路径。
- RobStride `0x7005` 控制模式读回超时属于独立的 CAN/电机通信问题，本次特征修复不会屏蔽或修复该 warning。该 warning 未解决时不应输入 `/start`。
- 本次修改没有改变 ACT 模型、数据集统计量、相机默认设备或 Rebot CAN 参数。

## 验证

已完成：

- `HF_HOME=/tmp/lerobot-hf-home UV_CACHE_DIR=/tmp/lerobot-uv-cache uv run pytest tests/test_rollout.py -q`
  - 结果：`50 passed`
- `UV_CACHE_DIR=/tmp/lerobot-uv-cache uv run ruff check src/lerobot/rollout/context.py src/lerobot/rollout/strategies/core.py src/lerobot/scripts/lerobot_rollout.py`
  - 结果：`All checks passed!`
- Rebot 特征静态检查确认观测和动作分别包含 10 个标量键。
- 已通过实际 rollout 日志确认原始错误发生在 normalizer 的 7/10 维状态输入处。

未完成或受限：

- 本次环境没有在真实电机控制模式读回正常的条件下完成完整 ACT 运动回归。
- RobStride `0x7005` readback timeout 仍需单独检查 CAN 波特率、设备 ID、host/feedback ID 和电机供电。
- 尚未用修复后的代码完成真实机器人 `/start` 全流程验证。

## 使用方式

使用当前源码启动 rollout：

```bash
uv run lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/train/act_Object_Storage_joint/checkpoints/050000/pretrained_model \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --device=cuda \
  --fps=30 \
  --interactive=true \
  --return_to_initial_position=true \
  --display_data=true
```

## 相关文件

- [src/lerobot/rollout/context.py](../../src/lerobot/rollout/context.py)
- [src/lerobot/rollout/strategies/core.py](../../src/lerobot/rollout/strategies/core.py)
- [src/lerobot/scripts/lerobot_rollout.py](../../src/lerobot/scripts/lerobot_rollout.py)
- [src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [third_party/reBotArm_control_py/config/rebotarm_rs.yaml](../../third_party/reBotArm_control_py/config/rebotarm_rs.yaml)
