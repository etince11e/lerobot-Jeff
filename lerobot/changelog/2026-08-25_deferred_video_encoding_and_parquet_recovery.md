# 延迟视频编码与数据集恢复修复

## 摘要

修复录制过程中视频编码阻塞、延迟编码在结束阶段破坏 Parquet 文件，以及恢复录制时无法继续处理临时帧的问题。录制默认改用 H.264 `ultrafast`，并支持将视频帧暂存到 episode 结束后统一编码。

## 用户可见问题

- 每条 episode 保存后需要等待很久，下一条 episode 才开始采集。
- 录制结束时出现 `IndexError: Invalid key: 10 is out of bounds for size 10`。
- 异常发生后，数据和 episode 元数据 Parquet 文件只有 `PAR1` 文件头，没有 footer，数据集无法加载。
- 从 AV1 默认编码切换到 H.264 后，旧视频与新视频不能直接拼接到同一个 MP4。

## 根因

1. 录制默认使用 `libsvtav1`，编码速度较慢；原来的 batch size 语义也没有提供“全部延迟到结束”的模式。
2. 延迟编码依赖仍处于写入状态的 Parquet metadata。结束阶段先编码、后关闭 writer 时，一旦编码路径失败，Parquet footer 没有落盘。
3. 批量编码使用 episode 的局部数据文件索引访问 `meta.episodes`，在跨 Parquet 文件或恢复场景下会把全局 episode index 当作单文件行号。
4. `concatenate_video_files()` 使用 stream copy，不能安全拼接 codec、像素格式或帧率不同的视频流。

## 修改内容

### 配置与录制流程

- [src/lerobot/configs/dataset.py](../../src/lerobot/configs/dataset.py) 将录制 RGB 默认编码设置为 H.264、CRF 23、`ultrafast`。
- `video_encoding_batch_size=0` 表示保留临时帧，在最终阶段统一编码；`1` 仍表示每条 episode 编码，正整数大于 1 表示周期性批量编码。
- [src/lerobot/scripts/lerobot_record.py](../../src/lerobot/scripts/lerobot_record.py) 和录制文档同步说明新的延迟编码行为。

### Parquet 生命周期与恢复

- [src/lerobot/datasets/dataset_writer.py](../../src/lerobot/datasets/dataset_writer.py) 在视频编码前关闭数据 Parquet writer，确保编码失败不会留下无 footer 的数据文件。
- [src/lerobot/datasets/dataset_metadata.py](../../src/lerobot/datasets/dataset_metadata.py) 增加可继续写入的 metadata flush；flush 后创建新的 metadata 文件，避免重新打开带 footer 的 Parquet 追加写入。
- 初始化 writer 时检测已保存 episode 对应的临时帧，因此录制进程中断后可以通过 `--resume=true` 继续编码，而不是丢弃这些帧。
- 批量编码重新从磁盘加载完整 episode metadata，并依据 `meta/episodes/chunk_index` 与 `file_index` 定位对应 Parquet 文件。

### 视频兼容性

- 在拼接前比较 codec、分辨率、帧率和像素格式。
- 如果编码流不兼容，则自动创建新的 video file，而不是把 AV1 与 H.264 混合写入同一个 MP4。

## 验证

- `tests/datasets/test_dataset_writer.py`：18 passed。
- 已在实际数据集副本上恢复两个缺失 footer 的 Parquet 文件，恢复 20 个 episode、20287 帧。
- 已实际解码 AV1/H.264 边界前后的帧，episode 9、10、19 均可读取，两个相机图像形状为 `(3, 480, 640)`。
- 原有 AV1 视频文件保持不变；episode 10–19 被编码到独立的 H.264 文件中。

## 注意事项与限制

- 本次修复没有自动上传或覆盖 Hugging Face Hub 上的数据集；本地恢复目录另保留了时间戳备份。
- H.264 文件通常比 AV1 更易实时或快速编码，但文件体积和压缩效率可能不同。
- 已存在的不同编码视频不会被重新编码；写入新 episode 时会自动按编码兼容性切换文件。

## 相关文件

- [src/lerobot/configs/dataset.py](../../src/lerobot/configs/dataset.py)
- [src/lerobot/datasets/dataset_metadata.py](../../src/lerobot/datasets/dataset_metadata.py)
- [src/lerobot/datasets/dataset_writer.py](../../src/lerobot/datasets/dataset_writer.py)
- [src/lerobot/datasets/lerobot_dataset.py](../../src/lerobot/datasets/lerobot_dataset.py)
- [src/lerobot/scripts/lerobot_record.py](../../src/lerobot/scripts/lerobot_record.py)
- [tests/datasets/test_dataset_metadata.py](../../tests/datasets/test_dataset_metadata.py)
- [tests/datasets/test_dataset_writer.py](../../tests/datasets/test_dataset_writer.py)
- [tests/datasets/test_video_encoding.py](../../tests/datasets/test_video_encoding.py)
