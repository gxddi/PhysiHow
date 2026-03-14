"""
Extract skeletal keypoints from exercise videos using MediaPipe Pose (Tasks API).
Outputs per-video sequences with shape (T, V, C): time, joints, coordinates (+ optional confidence).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from .skeleton_config import NUM_JOINTS, NUM_COORD_CHANNELS

# MediaPipe Tasks API (Pose Landmarker)
_POSE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"


def _get_pose_model_path() -> Path:
    """Return path to cached pose landmarker model; download if needed."""
    cache_dir = Path(__file__).resolve().parents[2] / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "pose_landmarker_lite.task"
    if path.is_file():
        return path
    import urllib.request
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_POSE_MODEL_URL, timeout=60) as resp:
        path.write_bytes(resp.read())
    return path


def _pose_result_to_keypoints(result, use_visibility: bool, num_joints: int = NUM_JOINTS) -> np.ndarray:
    """Convert PoseLandmarkerResult for one frame to (V, C) array."""
    C = 4 if use_visibility else 3
    kp = np.zeros((num_joints, C), dtype=np.float32)
    if not result.pose_landmarks or not result.pose_landmarks[0]:
        return kp
    landmarks = result.pose_landmarks[0]
    for i, lm in enumerate(landmarks):
        if i >= num_joints:
            break
        kp[i, 0] = lm.x
        kp[i, 1] = lm.y
        kp[i, 2] = lm.z
        if use_visibility:
            kp[i, 3] = getattr(lm, "visibility", 1.0) or 1.0
    return kp


def extract_keypoints_from_video(
    video_path: str | Path,
    max_frames: int | None = None,
    use_visibility: bool = True,
) -> np.ndarray:
    """
    Run MediaPipe Pose Landmarker on a video and return keypoint sequence (T, V, C).

    Args:
        video_path: Path to video file.
        max_frames: If set, cap the number of frames processed (for memory/speed).
        use_visibility: If True, C=4 (x, y, z, visibility); else C=3 (x, y, z).

    Returns:
        Array of shape (T, V, C) with V=NUM_JOINTS (33), float32.
        Missing poses yield zeros for that frame.
    """
    from mediapipe.tasks.python.core import base_options as base_options_lib
    from mediapipe.tasks.python.vision import pose_landmarker
    from mediapipe.tasks.python.vision.core import image as image_lib
    from mediapipe.tasks.python.vision.core import vision_task_running_mode as running_mode_lib

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    model_path = _get_pose_model_path()
    base_options = base_options_lib.BaseOptions(model_asset_path=str(model_path))
    options = pose_landmarker.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=running_mode_lib.VisionTaskRunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    landmarker = pose_landmarker.PoseLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    C = 4 if use_visibility else 3
    frames_list: list[np.ndarray] = []
    frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if max_frames is not None and len(frames_list) >= max_frames:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if rgb.dtype != np.uint8 or not rgb.flags.c_contiguous:
                rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
            mp_image = image_lib.Image(image_lib.ImageFormat.SRGB, rgb)
            timestamp_ms = int(frame_idx * 1000 / 30)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)
            kp = _pose_result_to_keypoints(result, use_visibility)
            frames_list.append(kp)
            frame_idx += 1
    finally:
        cap.release()
        landmarker.close()

    if not frames_list:
        return np.zeros((0, NUM_JOINTS, C), dtype=np.float32)

    return np.stack(frames_list, axis=0)


def get_keypoints_from_frame(
    frame_bgr: np.ndarray,
    landmarker,
    frame_timestamp_ms: int,
    use_visibility: bool = True,
) -> np.ndarray:
    """
    Run Pose Landmarker on a single BGR frame. Returns (V, C) keypoint array for one frame.
    Use with VIDEO mode and monotonically increasing frame_timestamp_ms (e.g. frame_index * 33).
    """
    from mediapipe.tasks.python.vision.core import image as image_lib

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    if rgb.dtype != np.uint8 or not rgb.flags.c_contiguous:
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    mp_image = image_lib.Image(image_lib.ImageFormat.SRGB, rgb)
    result = landmarker.detect_for_video(mp_image, frame_timestamp_ms)
    return _pose_result_to_keypoints(result, use_visibility)


def create_pose_landmarker():
    """Create a PoseLandmarker in VIDEO mode for reuse (e.g. webcam)."""
    from mediapipe.tasks.python.core import base_options as base_options_lib
    from mediapipe.tasks.python.vision import pose_landmarker
    from mediapipe.tasks.python.vision.core import vision_task_running_mode as running_mode_lib

    model_path = _get_pose_model_path()
    base_options = base_options_lib.BaseOptions(model_asset_path=str(model_path))
    options = pose_landmarker.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=running_mode_lib.VisionTaskRunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return pose_landmarker.PoseLandmarker.create_from_options(options)


def draw_pose_landmarks_on_frame(frame_bgr: np.ndarray, keypoints: np.ndarray) -> None:
    """
    Draw pose keypoints (V, 3) or (V, 4) in normalized [0,1] coords onto frame in-place.
    """
    h, w = frame_bgr.shape[:2]
    # Same connections as MediaPipe POSE_CONNECTIONS
    connections = [
        (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
        (9, 10), (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
        (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
        (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (27, 29), (27, 31),
        (24, 26), (26, 28), (28, 30), (28, 32), (25, 31), (26, 32),
    ]
    pts = []
    for i in range(min(keypoints.shape[0], NUM_JOINTS)):
        x, y = keypoints[i, 0], keypoints[i, 1]
        if 0 <= x <= 1 and 0 <= y <= 1:
            pts.append((int(x * w), int(y * h)))
        else:
            pts.append(None)
    for a, b in connections:
        if a < len(pts) and b < len(pts) and pts[a] is not None and pts[b] is not None:
            cv2.line(frame_bgr, pts[a], pts[b], (0, 255, 0), 2)
    for p in pts:
        if p is not None:
            cv2.circle(frame_bgr, p, 4, (0, 255, 255), -1)


def extract_keypoints_from_exercises_json(
    exercises_json_path: str | Path,
    data_dir: str | Path,
    out_dir: str | Path,
    max_frames_per_video: int | None = None,
    use_visibility: bool = True,
    skip_missing: bool = True,
) -> list[dict]:
    """
    Read an exercises JSON (list of exercises with videoPathLocal) and extract keypoints for each video.
    Saves one .npy file per video and returns a list of records.

    Args:
        exercises_json_path: Path to JSON with "exercises" array (each item has id, videoPathLocal, exerciseName, etc.).
        data_dir: Base directory for video_path_local (e.g. data/).
        out_dir: Directory to write keypoint .npy files (e.g. data/keypoints).
        max_frames_per_video: Cap frames per video (default None = no cap).
        use_visibility: Include visibility channel.
        skip_missing: If True, skip videos whose file is missing; else raise.

    Returns:
        List of dicts: { "sample_id", "keypoint_path", "label", "exercise_id", "exercise_name" }.
    """
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(exercises_json_path, encoding="utf-8") as f:
        data = json.load(f)

    exercises = data.get("exercises", [])
    label_to_id = {ex["id"]: i for i, ex in enumerate(exercises)}
    records: list[dict] = []

    for ex in tqdm(exercises, desc="Extracting keypoints"):
        ex_id = ex["id"]
        rel_path = ex.get("videoPathLocal", "")
        if not rel_path:
            if skip_missing:
                continue
            raise FileNotFoundError(f"No videoPathLocal for exercise {ex_id}")
        video_path = data_dir / rel_path.replace("/", os.sep)

        if not video_path.is_file():
            if skip_missing:
                continue
            raise FileNotFoundError(f"Video file not found: {video_path}")

        keypoints = extract_keypoints_from_video(
            video_path,
            max_frames=max_frames_per_video,
            use_visibility=use_visibility,
        )

        # Save as .npy: (T, V, C)
        out_name = Path(rel_path).stem + "_keypoints.npy"
        out_path = out_dir / out_name
        np.save(out_path, keypoints, allow_pickle=False)

        label = label_to_id[ex_id]
        records.append({
            "sample_id": ex_id,
            "keypoint_path": str(out_path),
            "label": label,
            "exercise_id": ex_id,
            "exercise_name": ex.get("exerciseName", ""),
        })

    return records


def main():
    parser = argparse.ArgumentParser(description="Extract keypoints from exercise videos (exercises.json)")
    parser.add_argument("--data-dir", type=str, default="data", help="Base data directory (contains exercises.json and exercises/)")
    parser.add_argument("--out-dir", type=str, default="data/keypoints", help="Output directory for .npy keypoint files")
    parser.add_argument("--exercises-json", type=str, default="exercises.json", help="Name of exercises JSON file inside data-dir")
    parser.add_argument("--max-frames", type=int, default=None, help="Max frames per video (default: all)")
    parser.add_argument("--no-visibility", action="store_true", help="Do not include visibility channel")
    parser.add_argument("--manifest", type=str, default=None, help="If set, write manifest JSON to this path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    exercises_path = data_dir / args.exercises_json
    if not exercises_path.is_file():
        raise SystemExit(f"Exercises JSON not found: {exercises_path}")

    records = extract_keypoints_from_exercises_json(
        exercises_path,
        data_dir=data_dir,
        out_dir=Path(args.out_dir),
        max_frames_per_video=args.max_frames,
        use_visibility=not args.no_visibility,
        skip_missing=True,
    )

    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"Wrote manifest to {manifest_path}")

    print(f"Extracted keypoints for {len(records)} videos.")


if __name__ == "__main__":
    main()
