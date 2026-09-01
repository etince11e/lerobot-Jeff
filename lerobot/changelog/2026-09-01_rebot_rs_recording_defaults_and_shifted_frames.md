# reBot RS 录制默认配置与 shifted-frame 数据配对

日期：2026-09-01

## 摘要

本次变更集中调整 reBot RS follower 的录制链路和现场默认配置，内容包括：

1. 更新头部和腕部相机的默认 V4L2 设备节点；
2. 放宽安全回零时的关节稳定判定阈值；
3. 为 `lerobot-record` 增加可选的 Xense shifted-frame 录制模式；
4. 更新录制与 rollout 命令示例，反映当前数据集和视频编码配置；
5. 增加 shifted-frame 以及默认同帧录制行为的自动化测试。

这些改动默认不会改变其他机器人或既有 reBot RS 录制行为：只有显式传入
`--shift_frame=true` 时，reBot RS 才会使用 shifted-frame 配对。

## 原始问题与背景

### 相机设备节点与当前硬件布局不一致

`RebotRSFollowerConfig` 中的默认相机节点仍指向 `/dev/video4` 和 `/dev/video2`。
在当前工作台布局下，头部相机和腕部相机分别对应 `/dev/video6` 与 `/dev/video9`，
因此不修改命令行参数时可能打开错误的摄像头或无法启动录制。

### 安全回零的稳定判定过于严格

`safe_home()` 默认使用 `0.01` 的关节误差阈值。真实硬件到达机械零位后仍可能存在
小幅反馈误差，过严的阈值会让回零在超时前无法确认完成，并在录制关闭流程中产生
不必要的失败告警。

### 录制数据需要与 Xense 的时间配对方式兼容

传统录制逻辑把同一控制 tick 捕获的 observation 和发送 action 写入同一帧：

```text
observation[t] + commanded_action[t]
```

Xense 数据处理使用 shifted-frame 语义，希望保存上一时刻的 observation，并将下一时刻
观测到的 TCP 状态作为 action：

```text
observation[t] + observed_tcp_state[t+1]
```

夹爪是有意保留的例外。物体接触可能阻止夹爪到达目标开度，因此 action 中的
`gripper.pos` 必须继续使用 Pico4 在 `t` 时刻发出的命令，而不是下一帧测得的夹爪位置。

## 修改后的行为

### 默认模式（保持兼容）

当 `shift_frame` 未设置或为 `false` 时，所有机器人（包括 reBot RS）仍按原有方式记录：

```text
observation[t] + robot.send_action() 返回的 action[t]
```

这里使用 `robot.send_action()` 的返回值，确保机器人端执行的裁剪或规范化结果进入数据集。

### reBot RS shifted-frame 模式

当同时满足以下条件时启用 shifted-frame：

- `dataset` 不为空；
- `shift_frame=true`；
- `robot.name == "rebot_rs_follower"`。

录制循环会缓存上一帧 observation 和上一帧实际发送的 action。在下一控制 tick：

1. 当前观测提供上一帧对应的 TCP action 字段；
2. 上一帧缓存的 `gripper.pos` 命令覆盖当前观测中的夹爪反馈；
3. 写入上一帧 observation 与组合后的 action；
4. 当前 observation 和当前发送 action 成为下一轮缓存。

首个控制 tick 只建立缓存，不写入数据集，因此 shifted-frame 录制的有效帧数比采样
观测少一帧。Pico4 触发 reset 时会清空缓存，避免把 reset 前后的状态错误拼接在一起。

## 具体实现

### 1. 更新 reBot RS 默认相机

在 [`config_rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py) 中：

| 相机 | 修改前 | 修改后 |
| --- | --- | --- |
| `head_camera` | `/dev/video4` | `/dev/video6` |
| `wrist_camera` | `/dev/video2` | `/dev/video9` |

分辨率、帧率、MJPG 编码和 V4L2 backend 均保持不变。

### 2. 放宽安全回零稳定阈值

在 [`rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py) 的
`safe_home()` 中，将默认 `settle_thresh` 从 `0.01` 调整为 `0.05`。该参数只影响
回零完成的稳定性判断，不改变目标 home pose、最大速度、发送频率、超时时间或夹爪目标。

### 3. 增加 `shift_frame` 配置

在 [`lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py) 的 `RecordConfig` 中
新增：

```text
shift_frame: bool = False
```

`record()` 将该配置传递给 `record_loop()`。通过机器人名称进行限定，避免该数据配对
语义意外影响 LeKiwi、SO-101 或其他录制设备。

### 4. 构造 shifted action 并校验 schema

新增 `_build_xense_shifted_action()`：

- TCP 等 action feature 从当前 observation 读取；
- 若 action schema 声明了 `gripper.pos`，则要求 commanded action 也包含该字段，
  并保留 commanded value；
- 任意 action feature 不存在于 observation 时立即抛出 `ValueError`，避免静默生成
  不完整的数据；
- 写入前仍通过 `build_dataset_frame()` 按数据集 schema 聚合字段。

### 5. 更新命令文档

在 [`client_commande.md`](../../src/lerobot/scripts/client_commande.md) 中：

- 录制示例切换到 `etince11e/Objects-Into-Box-0826`；
- 更新任务描述和录制 episode 数量（28）；
- 增加 H.264 视频编码及 streaming encoding 参数；
- 更新本地数据集路径；
- rollout 示例改用 `100000` checkpoint。

文档示例只反映推荐配置，不会自动改变运行时默认的 `shift_frame=false`。如需 Xense
配对，应在 `lerobot-record` 命令中额外加入：

```bash
--shift_frame=true
```

## 测试覆盖

在 [`tests/test_control_robot.py`](../../tests/test_control_robot.py) 中新增两项测试：

1. `test_rebot_rs_record_loop_uses_xense_shifted_frames`
   - 验证首帧缓存行为；
   - 验证 TCP action 使用下一帧 observation；
   - 验证 gripper action 保留上一帧 Pico4 命令；
   - 验证最终只写入两帧有效 shifted 数据。
2. `test_rebot_rs_record_loop_uses_same_tick_frames_by_default`
   - 验证 `shift_frame` 默认关闭；
   - 验证 reBot RS 在默认模式下仍写入同 tick observation/action。

测试使用 mock robot、mock teleoperator 和内存中的 `DatasetSpy`，不需要连接真实机械臂、
Pico4、CAN 总线或摄像头。

## 生命周期、错误处理与兼容性

- reset 操作会清空 shifted-frame 的 observation/action 缓存，避免跨 reset 配对；
- 缓存 action 使用 `dict(sent_action)` 保存，避免后续调用修改已缓存的可变映射；
- 缺少 observation feature 或 commanded `gripper.pos` 时显式失败，不写入不完整帧；
- shifted-frame 只在 reBot RS 且显式开启时生效，其他机器人和默认配置保持兼容；
- 该模式会丢弃每个录制阶段的最后一个尚未配对 observation。若下游要求严格保留所有
  采样时刻，应在数据集转换阶段另行处理尾帧；
- 相机节点是本机设备路径，迁移到其他机器时仍需根据 `v4l2-ctl --list-devices` 等
  信息确认 `/dev/video6` 和 `/dev/video9` 的映射。

## 验证状态

已完成静态检查和 mock 集成测试：

```text
uv run pytest tests/test_control_robot.py -svv --maxfail=1   9 passed
uv run pytest tests/test_control_robot.py -k 'rebot_rs_record_loop_uses'  2 passed
uv run ruff check（涉及文件）                                      通过
uv run ruff format --check（涉及文件）                             通过
git diff --check                                                   通过
```

测试通过时将 Hugging Face datasets 和 uv 的缓存目录重定向到 `/tmp`，以适应当前
沙箱环境。第一次未设置缓存目录的运行因 `/home/jeff/.cache` 为只读而无法创建锁文件，
随后通过临时缓存目录完成了同一测试文件的完整验证。

真实硬件录制仍需在具备 reBot RS、Pico4、对应相机节点和 CAN 适配器的环境中执行；
本次没有宣称已经验证 `/dev/video6`、`/dev/video9` 的实际设备映射或 `safe_home()` 的
机械运动效果。

## 相关文件

- [`src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
- [`src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/rebot_rs_follower.py)
- [`src/lerobot/scripts/lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py)
- [`src/lerobot/scripts/client_commande.md`](../../src/lerobot/scripts/client_commande.md)
- [`tests/test_control_robot.py`](../../tests/test_control_robot.py)
