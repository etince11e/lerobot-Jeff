# Pico4 + reBot RS `lerobot-record` 链路集成

日期：2026-08-25

## 摘要

本次变更参考 `lerobot-xense` 中 Pico4 + Flexiv 的录制启动和设备同步思路，
将 Pico4 遥操作器与 `rebot_rs_follower` 集成到 `lerobot-record`。

录制时现在会：

1. 先连接 Pico4，确认 VR 输入链路可用；
2. 连接并使能 reBot RS；
3. 依次移动到机械零位和配置的录制起始位；
4. 使用机械臂当前 TCP 四元数位姿初始化 Pico4 的绝对目标；
5. 在录制过程中响应右手柄 A 键，将机械臂回到起始位并重新同步 Pico4；
6. 退出时先安全回机械零位，再断开 Pico4 和机械臂。

本次变更还补充了录制配置、双语文档和无硬件生命周期测试。

## 原始问题

此前 `lerobot-record` 虽然已经导入了 `pico4`，但没有在录制脚本中显式导入
`rebot_rs_follower`，也没有针对这组设备实现专用启动流程。通用录制路径会直接
按普通设备顺序连接并进入 `record_loop()`，因此存在以下问题：

- Pico4 的绝对 TCP 目标没有从机械臂实际起始 TCP 位姿初始化；
- 录制启动过程没有复用 reBot RS 遥操作所需的 `safe_home()` / 起始位流程；
- Pico4 A 键回起始位只存在于 teleoperate 路径，录制过程中无法使用；
- 录制退出时没有保证 reBot RS 在断开驱动前先安全回零；
- `lerobot-record --help` 的机器人类型列表不包含 `rebot_rs_follower`。

## 修改后的数据流

```text
Pico4 connect
    ↓
reBot RS connect + enable
    ↓
safe_home()
    ↓
go_to_start_position()
    ↓
get_current_tcp_pose_quat()
    ↓
Pico4.reset_to_pose(...)
    ↓
record_loop()
    ├─ Pico4.get_action()
    ├─ A 键上升沿：回起始位并重新同步
    ├─ teleop/action processor
    ├─ reBot RS send_action()
    └─ observation + action 写入数据集
    ↓
退出：safe_home() → Pico4 disconnect → reBot RS disconnect
```

## 具体修改

### 1. `lerobot-record` 专用生命周期

在 [`src/lerobot/scripts/lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py) 中：

- 导入 `rebot_rs_follower`，使其通过 `RobotConfig` 注册到录制 CLI；
- 增加 `_is_rebot_rs_pico4()`，只对 `rebot_rs_follower + pico4` 组合启用专用逻辑；
- 增加 `_connect_record_devices()`，执行 Pico4 优先连接、RS 回零、起始位移动和 TCP 同步；
- 增加 `_reset_rebot_rs_pico4()`，处理 A 键触发的回起始位和目标重新锚定；
- 增加 `_cleanup_record_devices()`，在释放设备前尝试安全回机械零位，并兼容 RS 部分启动失败；
- 在 `record_loop()` 中处理 Pico4 reset button，并保持录制循环的节拍；
- 在 `record()` 中用专用启动和清理函数替换普通连接/断开路径。

### 2. 录制配置调整

在 [`src/lerobot/configs/dataset.py`](../../src/lerobot/configs/dataset.py) 中，
`DatasetRecordConfig.no_stamp` 默认值改为 `True`，录制命令默认保留用户指定的
`repo_id`，不会自动追加时间戳。需要唯一会话名时仍可显式设置
`--dataset.no_stamp=false`。

在 [`src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
中，将默认腕部相机设备路径改为 `/dev/video4`，匹配当前 RS 录制硬件接线。

### 3. 文档和示例

同步更新：

- [`README.md`](../../README.md)
- [`README-zh.md`](../../README-zh.md)
- [`examples/rebot_rs_pico4/README.md`](../../examples/rebot_rs_pico4/README.md)

文档新增 `lerobot-record` 命令、启动顺序、A 键行为、数据集 action/observation
字段和未连接相机时的参数说明。

### 4. 无硬件生命周期测试

在 [`tests/test_control_robot.py`](../../tests/test_control_robot.py) 增加
`test_rebot_rs_pico4_record_lifecycle_uses_safe_pose_sync()`，使用 fake Pico4 和
fake reBot RS 验证：

- 连接顺序为 Pico4 → RS；
- 启动顺序包含 `safe_home()`、`go_to_start_position()` 和 TCP 同步；
- A 键 reset 会重新读取 TCP 位姿并调用 `reset_to_pose()`；
- 清理顺序为 RS 安全回零 → Pico4 断开 → RS 断开。

## 兼容性与安全考虑

- 普通机器人与普通 teleoperator 组合仍使用原有 `teleop.connect()` →
  `robot.connect()` 路径，不改变其他录制设备的连接语义。
- RS 专用清理使用 `_arm` 资源存在性检查，因此即使机器人在连接过程中部分启动，
  也会尝试执行清理。
- 安全回零和回起始位是阻塞式点到点动作；录制开始、A 键 reset 和退出时应预留机械臂运动空间。
- A 键动作本身不写入数据集帧；下一次正常控制帧会使用重新同步后的 Pico4 目标。
- 本次变更没有修改 reBot RS 的 IK、MIT 重力补偿、CAN feedback 或电机控制参数。

## 验证

已完成：

```text
tests/test_control_robot.py                  7 passed
tests/robots/test_rebot_rs_follower.py       9 passed
ruff check                                    passed
ruff format --check                           passed
lerobot-record --help                         包含 rebot_rs_follower 和 pico4
```

测试使用 `HF_HOME=/tmp/lerobot-jeff-test-hf` 避免沙箱无法写入默认 Hugging Face
缓存目录的问题。测试覆盖的是配置、生命周期和 mock 行为，未连接真实 Pico4、CAN
适配器或 reBot RS 机械臂。

## 当前限制与后续工作

- 尚未完成真实硬件上的完整数据集录制验证，包括视频编码、长时间帧率稳定性和 A 键
  reset 期间的操作者体验。
- `/dev/video4` 是当前硬件默认值；如果部署机器的 V4L2 编号不同，需要通过机器人
  相机配置覆盖。
- `--dataset.no_stamp` 的默认行为改变可能影响依赖自动时间戳命名的旧录制脚本；需要
  自动命名时显式传入 `--dataset.no_stamp=false`。
- 后续可以增加一个不连接硬件的 `lerobot-record` dry-run 配置检查入口，但本次没有
  扩大命令语义范围。

## 相关文件

- [`src/lerobot/scripts/lerobot_record.py`](../../src/lerobot/scripts/lerobot_record.py)
- [`src/lerobot/configs/dataset.py`](../../src/lerobot/configs/dataset.py)
- [`src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py`](../../src/lerobot/robots/rebot_rs_follower/config_rebot_rs_follower.py)
- [`tests/test_control_robot.py`](../../tests/test_control_robot.py)
- [`README.md`](../../README.md)
- [`README-zh.md`](../../README-zh.md)
- [`examples/rebot_rs_pico4/README.md`](../../examples/rebot_rs_pico4/README.md)
