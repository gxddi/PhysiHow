"""
Preprocessing for skeleton keypoint sequences: temporal resampling, spatial normalization, augmentation.
Input/output shape: (T, V, C) with C >= 3 (x, y, z, ...).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .skeleton_config import NUM_JOINTS, HIP_INDICES


def temporal_resample(
    keypoints: np.ndarray,
    target_length: int,
    mode: str = "linear",
) -> np.ndarray:
    """
    Resample keypoint sequence to fixed length along time axis.

    Args:
        keypoints: (T, V, C)
        target_length: Desired number of frames.
        mode: 'linear' or 'nearest'.

    Returns:
        (target_length, V, C)
    """
    T, V, C = keypoints.shape
    if T == 0:
        return np.zeros((target_length, V, C), dtype=keypoints.dtype)
    if T == target_length:
        return keypoints

    # Resample each (T,) slice to target_length
    out = np.zeros((target_length, V, C), dtype=keypoints.dtype)
    for v in range(V):
        for c in range(C):
            out[:, v, c] = ndimage.zoom(
                keypoints[:, v, c],
                target_length / T,
                order=1 if mode == "linear" else 0,
                mode="nearest",
            )
    return out


def center_and_scale(
    keypoints: np.ndarray,
    center_joints: tuple[int, ...] = HIP_INDICES,
    scale_by: str = "torso",
) -> np.ndarray:
    """
    Translate so center_joints centroid is at origin; optionally scale by body size.

    Args:
        keypoints: (T, V, C), C >= 2 (x, y used).
        center_joints: Joint indices to average for center (e.g. left/right hip).
        scale_by: 'none' | 'torso' | 'max_extent'. If 'torso', scale so shoulder-hip
            distance is ~1; if 'max_extent', scale so max pairwise distance is ~1.

    Returns:
        (T, V, C) normalized in place copy.
    """
    out = keypoints.copy().astype(np.float32)
    T, V, C = out.shape
    xy = out[..., :2]

    # Center: subtract mean of center_joints over time
    center = np.mean(xy[:, center_joints, :], axis=(0, 1), keepdims=True)
    out[..., :2] = xy - center

    if scale_by == "none":
        return out

    # Scale: use first frame or mean over time for reference length
    ref = out[0] if T else out.mean(axis=0)
    if scale_by == "torso":
        # Shoulder midpoint to hip midpoint (indices 11,12 = shoulders; 23,24 = hips)
        s_mid = (ref[11, :2] + ref[12, :2]) / 2
        h_mid = (ref[23, :2] + ref[24, :2]) / 2
        length = np.linalg.norm(s_mid - h_mid)
    else:  # max_extent
        pts = ref[:, :2]
        d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
        length = np.max(d)
    if length > 1e-6:
        out[..., :2] = out[..., :2] / length
    if C >= 3:
        if length > 1e-6:
            out[..., 2] = out[..., 2] / length
    return out


def random_temporal_crop(keypoints: np.ndarray, target_length: int, rng: np.random.Generator | None = None) -> np.ndarray:
    """Random contiguous crop of length target_length. If T <= target_length, pad or return as-is."""
    rng = rng or np.random.default_rng()
    T, V, C = keypoints.shape
    if T <= target_length:
        return temporal_resample(keypoints, target_length, mode="linear")
    start = rng.integers(0, T - target_length + 1)
    return keypoints[start : start + target_length].copy()


def horizontal_flip_keypoints(keypoints: np.ndarray) -> np.ndarray:
    """
    Flip x-coordinate and swap left/right body joints.
    MediaPipe indices: 11,13,15,17,19,21 left arm; 12,14,16,18,20,22 right;
    23,25,27,29,31 left leg; 24,26,28,30,32 right; 1,2,3,7,9 left face; 4,5,6,8,10 right.
    """
    LEFT_RIGHT_PAIRS = [
        (1, 4), (2, 5), (3, 6), (7, 8), (9, 10),
        (11, 12), (13, 14), (15, 16), (17, 18), (19, 20), (21, 22),
        (23, 24), (25, 26), (27, 28), (29, 30), (31, 32),
    ]
    out = keypoints.copy()
    out[..., 0] = -out[..., 0]
    for i, j in LEFT_RIGHT_PAIRS:
        if i < out.shape[1] and j < out.shape[1]:
            out[:, [i, j], :] = out[:, [j, i], :]
    return out


def preprocess_sequence(
    keypoints: np.ndarray,
    target_length: int = 64,
    center: bool = True,
    scale: bool = True,
    augment_flip: bool = False,
    augment_temporal_crop: bool = False,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """
    Full preprocessing: temporal resample (or random crop), center, scale, optional flip.

    Args:
        keypoints: (T, V, C)
        target_length: Output number of frames.
        center: Apply center to hip.
        scale: Apply torso scaling.
        augment_flip: Random horizontal flip (train only).
        augment_temporal_crop: Use random crop instead of full resample (train only).
        rng: Random generator.

    Returns:
        (target_length, V, C) float32.
    """
    rng = rng or np.random.default_rng()
    if keypoints.size == 0:
        return np.zeros((target_length, keypoints.shape[1], keypoints.shape[2]), dtype=np.float32)

    if augment_temporal_crop:
        seq = random_temporal_crop(keypoints, target_length, rng)
    else:
        seq = temporal_resample(keypoints, target_length, mode="linear")

    if center or scale:
        seq = center_and_scale(
            seq,
            scale_by="torso" if scale else "none",
        )
    if augment_flip and rng.random() > 0.5:
        seq = horizontal_flip_keypoints(seq)
    return seq.astype(np.float32)
