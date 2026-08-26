# reBot rollout 非交互启动与 start pose 容差修复

日期：2026-08-26

## 修改内容

- 非 `--interactive=true` 的 rollout 现在也会在策略控制循环前移动到 `start_position`。
- interactive 和 non-interactive 两种模式共用同一个 start-pose 准备流程。
- Rebot 默认 start-pose 到位容差从严格的 `0.01` rad 放宽为 `0.05` rad。
- start-pose 反馈稳定等待时间显式配置为 `3.0` 秒，在放宽角度容差的同时给反馈缓存留出稳定时间。
- 容差和等待时间可通过 `RebotRSFollowerConfig` 的以下字段调整：
  - `start_position_settle_thresh`
  - `start_position_settle_timeout_s`
- 轨迹发送仍保留超时、取消和有限值反馈检查；放宽的是启动到位判定，不会跳过轨迹发送。

## 验证

- rollout、interactive 和 Rebot 相关测试：`109 passed`（本地相机设备 `/dev/video4` 与旧断言冲突的测试单独排除）。
- 受影响文件的 Ruff、typos、pyupgrade、bandit、mypy 和 pre-commit 检查全部通过。
