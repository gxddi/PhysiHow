"""
Live webcam demo: capture from camera, buffer keypoints, and classify the current motion
as the closest exercise in the template database. Press 'q' to quit.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

import cv2
import numpy as np

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from model.datasets.skeleton_config import NUM_JOINTS
from model.datasets.preprocessing import preprocess_sequence
from model.datasets.keypoint_extraction import create_pose_landmarker, get_keypoints_from_frame, draw_pose_landmarks_on_frame
from model.inference.dtw_match import load_templates, _match_query_to_templates


def main():
    parser = argparse.ArgumentParser(description="Live webcam exercise classification via DTW")
    parser.add_argument("--templates", type=str, default="data/dtw_templates", help="Path to template directory")
    parser.add_argument("--target-length", type=int, default=64, help="Sequence length for matching")
    parser.add_argument("--buffer-size", type=int, default=128, help="Max keypoint frames to buffer (>= target_length)")
    parser.add_argument("--interval", type=int, default=30, help="Run classification every N frames")
    parser.add_argument("--top-k", type=int, default=3, help="Show top-k matches on screen")
    parser.add_argument("--camera", type=int, default=0, help="Camera device index")
    args = parser.parse_args()

    templates_dir = Path(args.templates)
    if not (templates_dir / "templates.npz").is_file():
        raise SystemExit(f"Templates not found at {templates_dir}. Run: python -m model.inference.dtw_match --build-templates ...")

    templates, meta = load_templates(templates_dir)
    target_length = args.target_length
    buffer_size = max(args.buffer_size, target_length)
    interval = args.interval
    top_k = args.top_k

    landmarker = create_pose_landmarker()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        landmarker.close()
        raise SystemExit("Could not open webcam.")

    keypoint_buffer: deque = deque(maxlen=buffer_size)
    frame_count = 0
    last_result: list[tuple[str, str, float]] = []

    print("Live exercise matching. Press 'q' to quit.")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1
            timestamp_ms = frame_count * 33
            kp = get_keypoints_from_frame(frame, landmarker, timestamp_ms, use_visibility=True)
            keypoint_buffer.append(kp)

            if len(keypoint_buffer) >= target_length and frame_count % interval == 0:
                seq = np.stack(keypoint_buffer, axis=0)
                query = preprocess_sequence(
                    seq,
                    target_length=target_length,
                    center=True,
                    scale=True,
                    augment_flip=False,
                    augment_temporal_crop=False,
                )
                last_result = _match_query_to_templates(query, templates, meta, top_k, use_fastdtw=True)

            draw_pose_landmarks_on_frame(frame, kp[:, :3])

            if last_result:
                y_offset = 40
                for i, (eid, name, dist) in enumerate(last_result):
                    text = f"{i+1}. {name[:40]} ({dist:.1f})"
                    cv2.putText(frame, text, (20, y_offset + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "Collecting frames...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 0), 2)

            cv2.imshow("Exercise match", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
