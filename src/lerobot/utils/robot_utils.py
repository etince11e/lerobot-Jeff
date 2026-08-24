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

import logging
import platform
import time

import numpy as np


def get_logger(name: str, loglevel: str = "INFO") -> logging.Logger:
    """Return a standard Python logger configured with a named level."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, loglevel.upper(), logging.INFO))
    return logger


def precise_sleep(seconds: float, spin_threshold: float = 0.010, sleep_margin: float = 0.005):
    """
    Wait for `seconds` with better precision than time.sleep alone at the expense of more CPU usage.

    Parameters:
      - seconds: duration to wait
      - spin_threshold: if remaining <= spin_threshold -> spin; otherwise sleep (seconds). Default 10ms
      - sleep_margin: when sleeping leave this much time before deadline to avoid oversleep. Default 5ms

    Note:
        The default parameters are chosen to prioritize timing accuracy over CPU usage for the common 30 FPS use case.
    """
    if seconds <= 0:
        return
    if spin_threshold < 0:
        raise ValueError(f"spin_threshold must be >= 0, got {spin_threshold}")
    if sleep_margin < 0:
        raise ValueError(f"sleep_margin must be >= 0, got {sleep_margin}")

    system = platform.system()
    # On macOS and Windows the scheduler / sleep granularity can make
    # short sleeps inaccurate. Instead of burning CPU for the whole
    # duration, sleep for most of the time and spin for the final few
    # milliseconds to achieve good accuracy with much lower CPU usage.
    if system in ("Darwin", "Windows"):
        end_time = time.perf_counter() + seconds
        while True:
            remaining = end_time - time.perf_counter()
            if remaining <= 0:
                break
            # If there's more than a couple milliseconds left, sleep most
            # of the remaining time and leave a small margin for the final spin.
            if remaining > spin_threshold:
                # Sleep but avoid sleeping past the end by leaving a small margin.
                time.sleep(max(remaining - sleep_margin, 0))
            else:
                # Final short spin to hit precise timing without long sleeps.
                pass
    else:
        # On Linux time.sleep is accurate enough for most uses
        time.sleep(seconds)


def normalize_quaternion(q: np.ndarray, input_format: str = "wxyz") -> np.ndarray:
    """Normalize a quaternion and return it as [qw, qx, qy, qz]."""
    q = np.asarray(q, dtype=np.float32).reshape(-1)
    if len(q) != 4:
        raise ValueError(f"Quaternion must have 4 components, got {len(q)}")

    norm = np.linalg.norm(q)
    if norm < 1e-10:
        if input_format == "wxyz":
            return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        if input_format == "xyzw":
            return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        raise ValueError(f"Unknown input_format: {input_format}. Use 'wxyz' or 'xyzw'.")

    if abs(norm - 1.0) > 1e-6:
        q = q / norm

    if input_format == "wxyz":
        return q.astype(np.float32)
    if input_format == "xyzw":
        return np.array([q[3], q[0], q[1], q[2]], dtype=np.float32)
    raise ValueError(f"Unknown input_format: {input_format}. Use 'wxyz' or 'xyzw'.")


def slerp_quaternion(q1: np.ndarray, q2: np.ndarray, t: float, input_format: str = "wxyz") -> np.ndarray:
    """Spherical linear interpolation between two quaternions."""
    q1 = normalize_quaternion(q1, input_format=input_format)
    q2 = normalize_quaternion(q2, input_format=input_format)

    dot = float(np.dot(q1, q2))
    if dot < 0.0:
        q2 = -q2
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))

    if abs(dot) > 0.9995:
        return normalize_quaternion(q1 + t * (q2 - q1), input_format="wxyz")

    theta = np.arccos(dot)
    sin_theta = np.sin(theta)
    w1 = np.sin((1.0 - t) * theta) / sin_theta
    w2 = np.sin(t * theta) / sin_theta
    return normalize_quaternion(w1 * q1 + w2 * q2, input_format="wxyz")


def quaternion_to_matrix(pose: np.ndarray, input_format: str = "wxyz") -> np.ndarray:
    """Convert [x, y, z, quaternion] to a 4x4 transform matrix."""
    pose = np.asarray(pose, dtype=np.float64)
    if pose.shape != (7,):
        raise ValueError(f"Expected pose array of shape (7,), got {pose.shape}")

    x, y, z = pose[:3]
    qw, qx, qy, qz = normalize_quaternion(pose[3:7], input_format=input_format)
    return np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw), x],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw), y],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy), z],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def matrix_to_pose7d(matrix: np.ndarray, output_format: str = "wxyz") -> np.ndarray:
    """Convert a 4x4 transform matrix to [x, y, z, quaternion]."""
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4):
        raise ValueError(f"Expected matrix of shape (4, 4), got {matrix.shape}")

    x, y, z = matrix[:3, 3]
    rot = matrix[:3, :3]
    trace = np.trace(rot)
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        qw = 0.25 / s
        qx = (rot[2, 1] - rot[1, 2]) * s
        qy = (rot[0, 2] - rot[2, 0]) * s
        qz = (rot[1, 0] - rot[0, 1]) * s
    elif rot[0, 0] > rot[1, 1] and rot[0, 0] > rot[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rot[0, 0] - rot[1, 1] - rot[2, 2])
        qw = (rot[2, 1] - rot[1, 2]) / s
        qx = 0.25 * s
        qy = (rot[0, 1] + rot[1, 0]) / s
        qz = (rot[0, 2] + rot[2, 0]) / s
    elif rot[1, 1] > rot[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rot[1, 1] - rot[0, 0] - rot[2, 2])
        qw = (rot[0, 2] - rot[2, 0]) / s
        qx = (rot[0, 1] + rot[1, 0]) / s
        qy = 0.25 * s
        qz = (rot[1, 2] + rot[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + rot[2, 2] - rot[0, 0] - rot[1, 1])
        qw = (rot[1, 0] - rot[0, 1]) / s
        qx = (rot[0, 2] + rot[2, 0]) / s
        qy = (rot[1, 2] + rot[2, 1]) / s
        qz = 0.25 * s

    if output_format == "wxyz":
        return np.array([x, y, z, qw, qx, qy, qz], dtype=np.float32)
    if output_format == "xyzw":
        return np.array([x, y, z, qx, qy, qz, qw], dtype=np.float32)
    raise ValueError(f"Unknown output_format: {output_format}. Use 'wxyz' or 'xyzw'.")


def quaternion_to_rotation_6d(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    """Convert a quaternion to the first two columns of its rotation matrix."""
    return np.array(
        [
            1.0 - 2.0 * (qy * qy + qz * qz),
            2.0 * (qx * qy + qz * qw),
            2.0 * (qx * qz - qy * qw),
            2.0 * (qx * qy - qz * qw),
            1.0 - 2.0 * (qx * qx + qz * qz),
            2.0 * (qy * qz + qx * qw),
        ],
        dtype=np.float32,
    )


def rotation_6d_to_quaternion(r6d: np.ndarray, ensure_positive_w: bool = True) -> np.ndarray:
    """Convert a 6D rotation representation to [qw, qx, qy, qz]."""
    r6d = np.asarray(r6d, dtype=np.float64)
    if r6d.shape != (6,):
        raise ValueError(f"Expected r6d array of shape (6,), got {r6d.shape}")

    a1 = r6d[:3]
    a2 = r6d[3:6]
    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - np.dot(b1, a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    b3 = np.cross(b1, b2)
    pose = matrix_to_pose7d(
        np.array(
            [
                [b1[0], b2[0], b3[0], 0.0],
                [b1[1], b2[1], b3[1], 0.0],
                [b1[2], b2[2], b3[2], 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
        output_format="wxyz",
    )
    q = normalize_quaternion(pose[3:7], input_format="wxyz")
    if ensure_positive_w and q[0] < 0:
        q = -q
    return q
