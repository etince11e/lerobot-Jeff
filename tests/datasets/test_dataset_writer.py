#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contract tests for DatasetWriter."""

import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import torch
from PIL import Image

pytest.importorskip("datasets", reason="datasets is required (install lerobot[dataset])")
pytest.importorskip("pyarrow", reason="pyarrow is required (install lerobot[dataset])")

import pyarrow.parquet as pq  # noqa: E402

from lerobot.configs import VideoEncoderConfig
from lerobot.datasets.dataset_writer import _encode_video_worker
from lerobot.datasets.io_utils import load_episodes
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.utils import DEFAULT_IMAGE_PATH
from tests.fixtures.constants import DEFAULT_FPS, DUMMY_REPO_ID

SIMPLE_FEATURES = {
    "state": {"dtype": "float32", "shape": (6,), "names": None},
    "action": {"dtype": "float32", "shape": (6,), "names": None},
}


def _make_frame(features: dict, task: str = "Dummy task") -> dict:
    """Build a valid frame dict for the given features."""
    frame = {"task": task}
    for key, ft in features.items():
        if ft["dtype"] in ("image", "video"):
            frame[key] = np.random.randint(0, 256, size=ft["shape"], dtype=np.uint8)
        elif ft["dtype"] in ("float32", "float64"):
            frame[key] = torch.randn(ft["shape"])
        elif ft["dtype"] == "int64":
            frame[key] = torch.zeros(ft["shape"], dtype=torch.int64)
    return frame


# ── Existing encode_video_worker tests ───────────────────────────────


def test_encode_video_worker_forwards_video_encoder(tmp_path):
    """_encode_video_worker forwards video_encoder to encode_video_frames."""
    video_key = "observation.images.laptop"
    fpath = DEFAULT_IMAGE_PATH.format(image_key=video_key, episode_index=0, frame_index=0)
    img_dir = tmp_path / Path(fpath).parent
    img_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color="red").save(img_dir / "frame-000000.png")

    captured_kwargs = {}

    def mock_encode(imgs_dir, video_path, fps, **kwargs):
        captured_kwargs.update(kwargs)
        Path(video_path).parent.mkdir(parents=True, exist_ok=True)
        Path(video_path).touch()

    with patch("lerobot.datasets.dataset_writer.encode_video_frames", side_effect=mock_encode):
        _encode_video_worker(
            video_key,
            0,
            tmp_path,
            fps=30,
            video_encoder=VideoEncoderConfig(vcodec="h264", preset=None),
            encoder_threads=4,
        )

        assert captured_kwargs["video_encoder"].vcodec == "h264"
        assert captured_kwargs["encoder_threads"] == 4


def test_save_episode_video_rolls_file_when_codec_changes(tmp_path):
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=tmp_path / "codec_rollover",
        use_videos=True,
    )
    latest_path = dataset.root / dataset.meta.video_path.format(
        video_key=video_key, chunk_index=0, file_index=0
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.touch()
    temp_dir = dataset.root / "encoded_episode"
    temp_dir.mkdir()
    episode_path = temp_dir / "episode.mp4"
    episode_path.touch()
    dataset.meta.latest_episode = {
        "episode_index": [0],
        f"videos/{video_key}/chunk_index": [0],
        f"videos/{video_key}/file_index": [0],
        f"videos/{video_key}/from_timestamp": [0.0],
        f"videos/{video_key}/to_timestamp": [1.0],
    }
    av1_info = {
        "video.codec": "av1",
        "video.height": 64,
        "video.width": 96,
        "video.fps": DEFAULT_FPS,
        "video.pix_fmt": "yuv420p",
    }
    h264_info = {**av1_info, "video.codec": "h264"}

    with (
        patch("lerobot.datasets.dataset_writer.get_file_size_in_mb", return_value=1.0),
        patch("lerobot.datasets.dataset_writer.get_video_duration_in_s", return_value=1.0),
        patch("lerobot.datasets.dataset_writer.get_video_info", side_effect=[av1_info, h264_info]),
        patch("lerobot.datasets.dataset_writer.concatenate_video_files") as concatenate,
    ):
        metadata = dataset.writer._save_episode_video(video_key, 1, temp_path=episode_path)

    assert metadata[f"videos/{video_key}/file_index"] == 1
    assert metadata[f"videos/{video_key}/from_timestamp"] == 0.0
    assert metadata[f"videos/{video_key}/to_timestamp"] == 1.0
    assert (latest_path.parent / "file-001.mp4").is_file()
    concatenate.assert_not_called()


def test_encode_video_worker_default_video_encoder(tmp_path):
    """_encode_video_worker passes None video_encoder which encode_video_frames defaults."""
    video_key = "observation.images.laptop"
    fpath = DEFAULT_IMAGE_PATH.format(image_key=video_key, episode_index=0, frame_index=0)
    img_dir = tmp_path / Path(fpath).parent
    img_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color="red").save(img_dir / "frame-000000.png")

    captured_kwargs = {}

    def mock_encode(imgs_dir, video_path, fps, **kwargs):
        captured_kwargs.update(kwargs)
        Path(video_path).parent.mkdir(parents=True, exist_ok=True)
        Path(video_path).touch()

    with patch("lerobot.datasets.dataset_writer.encode_video_frames", side_effect=mock_encode):
        _encode_video_worker(video_key, 0, tmp_path, fps=30)

    assert captured_kwargs["video_encoder"] is None
    assert captured_kwargs["encoder_threads"] is None


# ── add_frame contracts ──────────────────────────────────────────────


def test_add_frame_increments_buffer_size(tmp_path):
    """Each add_frame() call increases episode_buffer['size'] by 1."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    assert dataset.writer.episode_buffer["size"] == 0

    dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    assert dataset.writer.episode_buffer["size"] == 1

    dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    assert dataset.writer.episode_buffer["size"] == 2


def test_add_frame_rejects_missing_feature(tmp_path):
    """add_frame() raises ValueError when a required feature is missing."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    with pytest.raises(ValueError, match="Missing features"):
        dataset.add_frame({"task": "Dummy task", "state": torch.randn(6)})
        # missing 'action'


# ── save_episode contracts ───────────────────────────────────────────


def test_save_episode_writes_parquet(tmp_path):
    """After save_episode(), at least one .parquet file exists under data/."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    for _ in range(3):
        dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    dataset.save_episode()

    parquet_files = list((tmp_path / "ds" / "data").rglob("*.parquet"))
    assert len(parquet_files) > 0


def test_save_episode_updates_counters(tmp_path):
    """After save_episode(), metadata counters are updated."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    for _ in range(5):
        dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    dataset.save_episode()

    assert dataset.meta.total_episodes == 1
    assert dataset.meta.total_frames == 5


def test_save_episode_resets_buffer(tmp_path):
    """After save_episode(), the episode buffer is reset."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    for _ in range(3):
        dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    dataset.save_episode()

    assert dataset.writer.episode_buffer["size"] == 0


def test_save_multiple_episodes(tmp_path):
    """Recording 3 episodes results in correct total counts."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    total_frames = 0
    for ep in range(3):
        n_frames = ep + 2  # 2, 3, 4
        for _ in range(n_frames):
            dataset.add_frame(_make_frame(SIMPLE_FEATURES))
        dataset.save_episode()
        total_frames += n_frames

    assert dataset.meta.total_episodes == 3
    assert dataset.meta.total_frames == total_frames


# ── clear / lifecycle ────────────────────────────────────────────────


def test_clear_resets_buffer(tmp_path):
    """clear_episode_buffer() resets the buffer size to 0."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    assert dataset.writer.episode_buffer["size"] == 1

    dataset.clear_episode_buffer()
    assert dataset.writer.episode_buffer["size"] == 0


def test_clear_removes_video_frame_staging_dir(tmp_path):
    """clear_episode_buffer() removes PNG staging dirs for video features."""
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=tmp_path / "ds",
        use_videos=True,
    )

    dataset.add_frame(_make_frame(features))
    video_staging_dir = (
        dataset.root
        / Path(DEFAULT_IMAGE_PATH.format(image_key=video_key, episode_index=0, frame_index=0)).parent
    )
    assert video_staging_dir.is_dir()

    dataset.clear_episode_buffer()

    assert dataset.writer.episode_buffer["size"] == 0
    assert not video_staging_dir.exists()


def test_batched_encoding_staging_survives_save(tmp_path):
    """The post-save clear must NOT delete video staging frames.

    With ``batch_encoding_size > 1`` the frames of already-saved episodes stay
    on disk until the batch encode runs; the encoder deletes them afterwards.
    A blanket switch of the post-save cleanup to ``camera_keys`` (as done in the
    discard path) would silently break batched encoding.
    """
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=tmp_path / "ds",
        use_videos=True,
        batch_encoding_size=2,
    )
    for _ in range(3):
        dataset.add_frame(_make_frame(features))

    staging_dir = dataset.writer._get_image_file_dir(0, video_key)
    assert staging_dir.is_dir()

    dataset.save_episode()  # first of a batch of 2: no encoding yet

    assert staging_dir.is_dir() and any(staging_dir.iterdir())


def test_zero_batch_size_defers_video_encoding_until_finalize(tmp_path):
    """A zero batch size keeps episodes collectable and encodes only at finalization."""
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=tmp_path / "ds",
        use_videos=True,
        batch_encoding_size=0,
    )
    dataset.add_frame(_make_frame(features))

    with patch.object(dataset.writer, "_batch_save_episode_video") as batch_encode:
        dataset.save_episode()

        batch_encode.assert_not_called()
        assert dataset.writer._episodes_since_last_encoding == 1
        assert dataset.writer._get_image_file_dir(0, video_key).is_dir()

        dataset.finalize()

    batch_encode.assert_called_once_with(0, 1)


def test_deferred_encoding_after_resume_reads_new_episode_metadata(tmp_path):
    """Regression: resumed episodes must be readable before final batch encoding."""
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    root = tmp_path / "resumed"
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=root,
        use_videos=True,
        batch_encoding_size=1,
    )
    dataset.add_frame(_make_frame(features))
    first_video_metadata = {
        "episode_index": 0,
        f"videos/{video_key}/chunk_index": 0,
        f"videos/{video_key}/file_index": 0,
        f"videos/{video_key}/from_timestamp": 0.0,
        f"videos/{video_key}/to_timestamp": 1.0,
    }
    with patch.object(dataset.writer, "_save_episode_video", return_value=first_video_metadata):
        dataset.save_episode()
    shutil.rmtree(dataset.writer._get_image_file_dir(0, video_key))
    dataset.finalize()

    resumed = LeRobotDataset.resume(
        DUMMY_REPO_ID,
        root=root,
        batch_encoding_size=0,
    )
    resumed.add_frame(_make_frame(features))
    resumed.save_episode()

    def save_resumed_video(_video_key: str, episode_index: int) -> dict:
        assert resumed.writer._meta.latest_episode["episode_index"] == [0]
        return {
            "episode_index": episode_index,
            f"videos/{video_key}/chunk_index": 0,
            f"videos/{video_key}/file_index": 1,
            f"videos/{video_key}/from_timestamp": 0.0,
            f"videos/{video_key}/to_timestamp": 1.0,
        }

    with patch.object(resumed.writer, "_save_episode_video", side_effect=save_resumed_video):
        resumed.finalize()

    episodes = load_episodes(root)
    assert len(episodes) == 2
    assert episodes[1][f"videos/{video_key}/file_index"] == 1


def test_periodic_batch_encoding_keeps_parquet_files_readable(tmp_path):
    """Metadata checkpoints must preserve data and consistent video timestamp types."""
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    root = tmp_path / "periodic"
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=root,
        use_videos=True,
        batch_encoding_size=2,
    )

    def save_video(_video_key: str, episode_index: int) -> dict:
        return {
            "episode_index": episode_index,
            f"videos/{video_key}/chunk_index": 0,
            f"videos/{video_key}/file_index": 0,
            f"videos/{video_key}/from_timestamp": episode_index / 3,
            f"videos/{video_key}/to_timestamp": (episode_index + 1) / 3,
        }

    with patch.object(dataset.writer, "_save_episode_video", side_effect=save_video):
        for _ in range(4):
            dataset.add_frame(_make_frame(features))
            dataset.save_episode()
        dataset.finalize()

    episodes = load_episodes(root)
    data_rows = sum(pq.ParquetFile(path).metadata.num_rows for path in root.rglob("data/**/*.parquet"))
    assert episodes["episode_index"] == [0, 1, 2, 3]
    assert episodes[f"videos/{video_key}/from_timestamp"] == pytest.approx([0, 1 / 3, 2 / 3, 1])
    assert data_rows == 4


def test_encoding_failure_does_not_leave_parquet_without_footer(tmp_path):
    """Deferred encoding failures must leave frame data and episode metadata readable."""
    video_key = "observation.images.cam"
    features = {
        video_key: {
            "dtype": "video",
            "shape": (64, 96, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {"dtype": "float32", "shape": (2,), "names": None},
    }
    root = tmp_path / "failed_encoding"
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID,
        fps=DEFAULT_FPS,
        features=features,
        root=root,
        use_videos=True,
        batch_encoding_size=0,
    )
    dataset.add_frame(_make_frame(features))
    dataset.save_episode()

    with (
        patch.object(dataset.writer, "_batch_save_episode_video", side_effect=RuntimeError("encode failed")),
        pytest.raises(RuntimeError, match="encode failed"),
    ):
        dataset.finalize()

    assert sum(pq.ParquetFile(path).metadata.num_rows for path in root.rglob("data/**/*.parquet")) == 1
    assert len(load_episodes(root)) == 1


def test_finalize_is_idempotent(tmp_path):
    """Calling finalize() twice does not raise."""
    dataset = LeRobotDataset.create(
        repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=SIMPLE_FEATURES, root=tmp_path / "ds"
    )
    for _ in range(3):
        dataset.add_frame(_make_frame(SIMPLE_FEATURES))
    dataset.save_episode()

    dataset.finalize()
    dataset.finalize()  # second call should not raise


def test_finalize_then_read_roundtrip(tmp_path):
    """Write data, finalize, re-open, and verify data matches."""
    root = tmp_path / "roundtrip"
    features = {"state": {"dtype": "float32", "shape": (2,), "names": None}}
    dataset = LeRobotDataset.create(repo_id=DUMMY_REPO_ID, fps=DEFAULT_FPS, features=features, root=root)

    # Record known values
    known_states = []
    for i in range(5):
        state = torch.tensor([float(i), float(i * 10)])
        known_states.append(state)
        dataset.add_frame({"task": "Test task", "state": state})
    dataset.save_episode()
    dataset.finalize()

    # Read back
    for i in range(5):
        item = dataset[i]
        assert torch.allclose(item["state"], known_states[i], atol=1e-5)
