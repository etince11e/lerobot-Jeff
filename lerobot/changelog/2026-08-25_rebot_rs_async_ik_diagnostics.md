# reBot RS 异步 IK 与控制延迟诊断修复

日期：2026-08-25

## 摘要

本记录覆盖本轮除 `dq_des` 外的另一组修改：将 reBot RS follower 的 IK 求解从遥操作线程中移出，改为 latest-only mailbox + 独立 IK worker，并增加请求排队、求解耗时、控制回调耗时、CAN 错误和命令跟踪误差诊断。

`dq_des` 速度参考没有纳入本记录。

## 原始问题

旧路径在 `send_action()` 中直接执行 IK：

```text
Pico4 action
    ↓
同步 solve_ik()
    ↓
发布 q_target
    ↓
返回遥操作主循环
```

当一次 IK 求解耗时超过手柄采样周期时：

- 遥操作主循环无法稳定维持目标频率；
- 新的 Pico4 姿态不能及时采样；
- 机械臂继续执行滞后的目标；
- 如果使用普通 FIFO 队列，会积累过时手部姿态并产生拖尾；
- IK 失败时只能继续保持旧关节目标，但缺少足够的时延和丢弃原因可观测性。

## 修改后的数据流

```text
遥操作线程
    ├─ 转换 TCP 目标
    ├─ 覆盖 latest-only IK mailbox
    └─ 立即返回

IK worker
    ├─ 取出最新请求
    ├─ 独占 Pinocchio Data 求解
    ├─ 发布同一 epoch 内完成的有效结果
    └─ 丢弃跨生命周期 epoch 的结果

控制线程
    └─ 持续发送最近一次有效的关节目标
```

## 具体修改

### 1. latest-only IK mailbox

在 [rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py) 中使用 `threading.Condition`、单槽 `_ik_request` 和独立 worker：

- 新请求覆盖尚未开始计算的旧请求；
- 不建立无限 FIFO；
- 遥操作线程不等待 IK；
- `_ik_request_seq` 用于记录输入顺序和诊断；
- `_ik_epoch` 用于回零、复位、断开等生命周期失效边界。

### 2. 同 epoch 结果发布

正在计算的请求不因为同一 epoch 内出现新请求而自动失效。例如 A 正在求解时 B 到达，A 完成后仍可以先发布，随后 worker 继续处理 mailbox 中的最新请求。

只有当生命周期 epoch 发生变化时，旧结果才会被丢弃，避免回零或断开后的旧 IK 结果覆盖新的安全目标。

### 3. Pinocchio Data 线程隔离

IK worker 使用自己的 Pinocchio `Data`。MIT 重力计算另建独立 dynamics `Data`，避免 IK 和动力学计算同时修改同一个可变 Pinocchio 缓存。

### 4. 延迟和控制诊断

新增或完善 `get_latency_snapshot()`，记录：

| 指标 | 含义 |
|---|---|
| `ik_queue_ms` | 请求进入 mailbox 到开始求解的时间 |
| `ik_solve_ms` | 最近一次 IK 求解耗时 |
| `ik_iterations` | 最近一次求解迭代次数 |
| `ik_request_seq` / `ik_latest_seq` | 当前和最新请求序号 |
| `ik_published_total` | 已发布有效 IK 结果总数 |
| `ik_dropped_total` | 被丢弃的 IK 结果总数 |
| `control_callback_ms` | 控制回调执行耗时 |
| `command_actual_error_rad` | 发送命令与实际位置的最大关节误差 |
| `can_* ` | SDK 提供的发送错误、feedback sweep 和 cache 诊断 |

Pico4 + reBot RS teleoperation loop 每约 0.5 秒输出一次这些指标，用于判断是 Pico 输入延迟、IK 排队、控制回调超时还是 CAN 错误造成的运动不连续。

### 5. 生命周期清理

断开时按以下顺序停止资源：

```text
停止位置对比诊断线程
    ↓
停止 IK worker
    ↓
停止 feedback/control worker
    ↓
断开执行器和相机
```

这样可以避免后台线程在模型、CAN controller 或 motor object 已经释放后继续访问资源。

## 配置变化

RS follower 配置增加并校验：

- `control_rate_hz`
- `feedback_rate_hz`
- `gravity_compensation_enabled`
- `gravity_compensation_scale`
- `position_compare_enabled`
- `position_compare_motor_name`
- `position_compare_interval_s`
- `position_compare_timeout_ms`

这些配置的具体反馈和重力补偿说明分别见：

- [rebot_rs_type2_feedback.md](./2026-08-25_rebot_rs_type2_feedback.md)
- [rebot_rs_mit_gravity_compensation.md](./2026-08-25_rebot_rs_mit_gravity_compensation.md)

## 验证

已完成：

- 相关 Python 文件通过 `py_compile`；
- `git diff --check` 通过；
- 保留并更新异步 IK worker 的成功、失败、epoch 失效和 latest-only mailbox 测试；
- 新增控制回调发送重力前馈的测试；
- 新增 Type-2 cache-only feedback 和关闭 feedback sweep 的测试。

完整 pytest 未在当前环境运行，原因是环境缺少项目依赖，已出现：

```text
ModuleNotFoundError: No module named 'huggingface_hub'
```

因此本记录不声称已通过完整测试套件，也不把静态检查等同于实机安全验证。

## 有意未修改与剩余限制

1. `dq_des` 速度参考完全不属于本记录。
2. 当前仍没有完整的在线速度、加速度和 jerk 限制器。
3. IK worker 只保证 latest-only 输入，不保证每个 Pico4 帧都产生一个 IK 结果。
4. 控制频率是否稳定仍需结合 `control_callback_ms`、CAN 错误和实际总线负载验证。
5. 软件诊断不能替代硬件急停、驱动器保护、机械限位和现场风险控制。

## 相关文件

- [rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [config_rebot_rs_follower.py](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
- [test_rebot_rs_follower.py](../../tests/robots/test_rebot_rs_follower.py)
- [test_rebotarm_feedback_cache.py](../../tests/robots/test_rebotarm_feedback_cache.py)
- [rebotarm.py](../../third_party/reBotArm_control_py/reBotArm_control_py/actuator/rebotarm.py)
