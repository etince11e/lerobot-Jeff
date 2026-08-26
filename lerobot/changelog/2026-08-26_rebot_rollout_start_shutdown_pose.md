# reBot rollout 启动位姿与退出回零修复

日期：2026-08-26

## 摘要

修复 `rebot_rs_follower` 在交互式 rollout 中输入 `/start` 后直接发送第一帧策略动作，以及 Ctrl+C/`/stop` 没有回机械零位的问题。

## 修改内容

- 每个 rollout segment 在策略恢复前先移动到配置的 `start_position`。
- start pose 移动失败、超时或被停止信号取消时，不启动策略控制循环。
- `/reset` 继续使用 `reset_to_initial_position()` 回到 start pose。
- `/stop` 和第一次 Ctrl+C 在断开硬件前调用 `safe_home()` 回到配置的 `home_position`。
- `_move_to_joint_target()` 现在返回明确的成功状态；轨迹超时或到位确认超时不会再误报 `reached`。
- 新增 `START_FAILED` 生命周期事件，交互终端会明确提示策略未启动。

## 验证

- `tests/test_rollout.py`、`tests/test_interactive_rollout.py` 与 Rebot 测试：`109 passed`（本地 `/dev/video4` 用户配置与旧相机断言不相关，单独排除）。
- 受影响文件的 Ruff、typos、pyupgrade、bandit、mypy 和 pre-commit 检查全部通过。

## 安全边界

第一次 Ctrl+C 只能保证 Python 正常收到信号并进入清理流程时尝试回零；第二次 Ctrl+C、`kill -9`、进程崩溃或断电无法依赖该软件回位，仍需使用硬件急停和驱动器保护。
