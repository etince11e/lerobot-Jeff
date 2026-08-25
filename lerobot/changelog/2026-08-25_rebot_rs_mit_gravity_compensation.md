# reBot RS MIT 重力补偿与启动保持修复

日期：2026-08-25

## 摘要

本次修改修复 reBot RS follower 切换到 MIT 控制后，在启动移动到 `start_position` 附近出现以下问题：

- 机械臂到达目标后，启动流程可能继续停顿约数秒；
- 机械臂在保持阶段可能突然下坠；
- MIT 控制此前只发送位置目标，没有向电机提供抵消机械臂自重的前馈力矩。

修复后的 MIT 控制会使用 Pinocchio 根据当前关节反馈计算广义重力向量 `g(q)`，并通过 MIT 命令的 `tau` 字段发送重力前馈。重力计算使用独立的 Pinocchio `Data`，避免与异步 IK 线程共享可变缓存。

本次变更包含软件级验证，但尚未在真实机械臂上完成重力补偿倍率、负载模型和长时间稳定性的最终验证。因此本文记录的是已完成的代码修复，不将实机下坠问题表述为已经完全闭环。

## 原始现象

启动 PICO4 与 reBot RS 遥操作时，程序依次执行：

```text
连接 PICO4
  ↓
连接并使能 reBot RS
  ↓
safe_home()
  ↓
go_to_start_position()
  ↓
等待实际关节位置进入 settle 阈值
  ↓
进入遥操作循环
```

机械臂到达 start pose 后，`_move_to_joint_target()` 会继续读取同步关节反馈，最多等待 3 秒，确认最大关节误差小于 `settle_thresh=0.01 rad`。MIT 模式下，如果机械臂因自重产生静态偏差，误差可能无法及时进入阈值，因此用户看到“到位后卡住几秒”。

POS_VEL 模式不明显，是因为电机内部位置/速度控制环能持续抵抗静态偏差；此前的 MIT 路径则只发送位置目标，`tau` 使用 SDK 默认值零，缺少重力前馈。

## 根因

### 1. MIT 命令没有重力前馈

旧控制路径等价于：

```python
arm_group.send_mit(q_command)
```

SDK 会为未提供的参数补零，因此控制律中前馈力矩为：

```text
tau_feedforward = 0
```

机械臂只能依赖 MIT 的位置刚度 `Kp` 和速度阻尼 `Kd` 抵抗重力。对于肩部、肘部等承载较大的关节，这可能导致持续位置偏差或下坠。

### 2. settle 等待暴露了静态位置误差

启动停顿不是额外的定时 sleep，而是启动轨迹完成后的到位检查。若 MIT 保持误差大于 `0.01 rad`，检查会持续到 3 秒截止时间。POS_VEL 下更容易迅速满足阈值，所以之前通常感受不到这段等待。

### 3. Pinocchio `Data` 不能跨线程共享

异步 IK worker 已经使用一份 Pinocchio `Data`。重力向量计算同样会修改 `Data` 内部缓存，如果 500 Hz 控制线程与 IK worker 共用同一个实例，会产生数据竞争和不可预测结果。

## 修改设计

### 控制关系

修改前：

```text
q_command
   ↓
MIT position PD
   ↓
tau_ff = 0
```

修改后：

```text
Type-2/RX cache 中的 q_actual
   ↓
Pinocchio computeGeneralizedGravity
   ↓
tau_g = scale × g(q_actual)
   ↓
MIT(position=q_command, tau=tau_g)
```

重力力矩根据实际关节反馈而不是目标位置计算，避免在跟踪误差较大时使用不对应当前构型的前馈值。

## 具体实现

### 1. 增加 MIT 重力补偿配置

在 [config_rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py:40) 中：

- 将 `arm_control_mode` 默认值改为 `mit`；
- 增加 `gravity_compensation_enabled: bool = True`；
- 增加 `gravity_compensation_scale: float = 1.0`；
- 校验补偿倍率必须为有限、非负数。

运行时可通过 CLI 调整：

```bash
--robot.gravity_compensation_enabled=true \
--robot.gravity_compensation_scale=0.5
```

虽然默认倍率为 `1.0`，首次实机调试建议从 `0.5` 开始，根据机械臂负载、URDF 惯性参数和实际保持表现逐步提高。

### 2. 引入 Pinocchio 重力计算接口

在 [rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py:52) 的 SDK 延迟导入中加入：

```python
compute_generalized_gravity
```

该接口复用 `reBotArm_control_py.dynamics` 已有实现，不在 follower 内重复实现动力学公式。

### 3. 为控制线程创建独立动力学缓存

连接机器人时，在 [rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py:244) 创建：

```python
self._dynamics_data = self._model.createData()
```

职责划分为：

| 数据对象         | 所属线程  | 用途             |
| ---------------- | --------- | ---------------- |
| `_data`          | IK worker | 异步逆运动学     |
| `_dynamics_data` | 控制线程  | 广义重力力矩计算 |

断开连接时会清空 `_dynamics_data`，避免生命周期结束后继续引用模型缓存。

### 4. 在 MIT 控制回调中发送 `tau_g`

在 [rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py:434) 中，MIT 路径现在执行：

1. 非阻塞读取当前关节位置缓存；
2. 将受控关节补齐到 Pinocchio 模型维度；
3. 计算 `compute_generalized_gravity(model, q, data)`；
4. 截取机械臂受控关节；
5. 乘以 `gravity_compensation_scale`；
6. 调用 `send_mit(q_command, tau=tau)`。

如果重力计算异常：

- 控制循环不会因为异常直接退出；
- 本次命令退化为零前馈力矩；
- 异常日志只在首次失败时完整记录，避免高频控制线程刷屏。

### 5. MIT 反馈路径配合

当前 MIT 模式使用 MotorBridge Type-2 响应维护 RX 状态缓存，并避免启动周期性的同步 `0x7019 mechPos` feedback sweep。相关连接策略位于 [rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py:279)。

这样做的目的是让 500 Hz MIT 控制循环读取非阻塞缓存，避免在重力计算前逐电机同步查询 CAN。POS_VEL 兼容路径仍保留原 feedback sweep，尚未改变其反馈语义。

底层 SDK 同时保留可选的 Type-2 与 `mechPos` 对比诊断，用于实机确认缓存关节位置的方向、单位和偏置是否正确。

### 6. 文档和测试

- [README-zh.md](/home/jeff/lerobot-rebot/lerobot-Jeff/README-zh.md:183) 和 [README.md](/home/jeff/lerobot-rebot/lerobot-Jeff/README.md:181) 增加 MIT 重力补偿参数说明；
- [test_rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/tests/robots/test_rebot_rs_follower.py:223) 增加 MIT 控制发送重力前馈力矩的测试；
- 测试同时确认 reBot RS follower 默认控制模式为 MIT。

## 安全与兼容性

### 保留 POS_VEL 兼容路径

没有删除 POS_VEL 代码。需要回退时仍可显式指定：

```bash
--robot.arm_control_mode=posvel
```

重力补偿只在 MIT 路径生效。

### 实机调参注意事项

重力模型依赖 URDF 中的质量、质心和惯性参数。模型误差、末端工具、线缆拉力和夹爪负载都可能使 `1.0 × g(q)` 与真实需求不一致。

建议实机首次验证时：

1. 准备急停或随时断使能；
2. 使用较低补偿倍率，例如 `0.5`；
3. 观察是否出现主动上抬、振荡或关节力矩突变；
4. 再逐步调整到 `0.8`、`1.0`；
5. 同时观察 `q_command - q_actual`、CAN send error 和 Type-2/mechPos 对比结果。

不得仅依靠软件测试认定力矩方向和倍率已适合所有硬件。

## 验证结果

已完成：

- 手动执行 `tests/robots/test_rebot_rs_follower.py` 中 9 个不需要 pytest fixture 的测试函数，全部通过；
- 新增的 `test_mit_control_sends_gravity_feedforward_torque` 验证 `compute_generalized_gravity()` 的结果被传入 `send_mit(..., tau=...)`；
- follower、测试文件以及嵌套 SDK 相关 Python 文件通过 `compileall`；
- 父仓库 `git diff --check` 通过；
- 嵌套 SDK 在其 CRLF 文件约定下通过 whitespace diff 检查。

未完成：

- 未在真实 reBot RS 上完成重力力矩方向、倍率和持续保持测试；
- 未执行标准 pytest 流程。项目 `.venv` 当前没有安装 `pytest`；系统 pytest 加载仓库 `conftest.py` 时因缺少 `huggingface_hub` 失败，报错为：

  ```text
  ModuleNotFoundError: No module named 'huggingface_hub'
  ```

## 仍需关注的问题

- 启动 settle 最长仍为 3 秒；本次没有移除保护逻辑。重力补偿正确后应更快满足阈值，但若反馈误差仍大，等待仍会跑满；
- 当前默认控制频率为 500 Hz，需要结合 `[LATENCY] control=` 和 CAN 错误统计确认计算重力后仍能满足周期；
- 未对 joint2/joint3 使用 SDK 示例中的额外 `1.55` 倍补偿。是否需要关节独立倍率必须由实机测量决定；
- 夹爪继续使用 MIT 位置保持，但当前未为夹爪计算重力前馈；
- 如果 Type-2 缓存的单位、符号或更新时间不正确，重力向量也会错误，应先使用可选位置对比诊断确认。

## 相关文件

- [src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
- [src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [tests/robots/test_rebot_rs_follower.py](/home/jeff/lerobot-rebot/lerobot-Jeff/tests/robots/test_rebot_rs_follower.py)
- [third_party/reBotArm_control_py/reBotArm_control_py/dynamics/inverse_dynamics.py](/home/jeff/lerobot-rebot/lerobot-Jeff/third_party/reBotArm_control_py/reBotArm_control_py/dynamics/inverse_dynamics.py)
- [third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py](/home/jeff/lerobot-rebot/lerobot-Jeff/third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py)
- [README-zh.md](/home/jeff/lerobot-rebot/lerobot-Jeff/README-zh.md)
- [README.md](/home/jeff/lerobot-rebot/lerobot-Jeff/README.md)
