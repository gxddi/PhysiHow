"""
DTW-based exercise matcher: build templates from dataset videos, match new videos to nearest exercise.
No deep learning; uses keypoint extraction + preprocessing + Dynamic Time Warping.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from model.datasets.keypoint_extraction import extract_keypoints_from_video
from model.datasets.preprocessing import preprocess_sequence

try:
    from fastdtw import fastdtw
    from scipy.spatial.distance import euclidean
    HAS_FASTDTW = True
except ImportError:
    HAS_FASTDTW = False


def _flatten_sequence(seq: np.ndarray) -> np.ndarray:
    """(T, V, C) -> (T, V*C) for DTW."""
    T, V, C = seq.shape
    return seq.reshape(T, -1).astype(np.float64)


def _dtw_exact(seq1: np.ndarray, seq2: np.ndarray) -> float:
    """Exact DTW distance (O(T1*T2)) with Euclidean local cost. seq1, seq2: (T, D)."""
    from scipy.spatial.distance import cdist
    T1, T2 = seq1.shape[0], seq2.shape[0]
    if T1 == 0 or T2 == 0:
        return float("inf")
    # cost matrix
    C = cdist(seq1, seq2, metric="euclidean")
    D = np.full((T1 + 1, T2 + 1), np.inf)
    D[0, 0] = 0
    for i in range(1, T1 + 1):
        for j in range(1, T2 + 1):
            D[i, j] = C[i - 1, j - 1] + min(D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])
    return float(D[T1, T2])


def dtw_distance(seq1: np.ndarray, seq2: np.ndarray, use_fastdtw: bool = True) -> float:
    """
    DTW distance between two keypoint sequences (T, V, C). Lower = more similar.
    Flattens to (T, V*C) and uses Euclidean local cost.
    """
    a = _flatten_sequence(seq1)
    b = _flatten_sequence(seq2)
    if use_fastdtw and HAS_FASTDTW:
        dist, _ = fastdtw(a, b, dist=euclidean)
        return float(dist)
    return _dtw_exact(a, b)


def build_templates(
    data_dir: str | Path,
    exercises_json_path: str | Path,
    out_dir: str | Path,
    target_length: int = 64,
    skip_missing: bool = True,
    max_videos: int | None = None,
) -> int:
    """
    Build template store from exercises.json: one template per exercise video.
    Writes templates.npz and templates_meta.json to out_dir. Returns number of templates built.
    If max_videos is set, only the first max_videos exercises (with valid videos) are used.
    """
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(exercises_json_path, encoding="utf-8") as f:
        data = json.load(f)
    exercises = data.get("exercises", [])
    if max_videos is not None:
        exercises = exercises[:max_videos]

    templates_list: list[np.ndarray] = []
    meta_list: list[dict] = []

    for ex in exercises:
        ex_id = ex.get("id", "")
        rel_path = ex.get("videoPathLocal", "")
        if not rel_path:
            if skip_missing:
                continue
            raise FileNotFoundError(f"No videoPathLocal for {ex_id}")
        video_path = (data_dir / rel_path).resolve()
        if not video_path.is_file():
            if skip_missing:
                continue
            raise FileNotFoundError(f"Video not found: {video_path}")

        try:
            keypoints = extract_keypoints_from_video(video_path, use_visibility=True)
        except Exception as e:
            if skip_missing:
                continue
            raise RuntimeError(f"Keypoint extraction failed for {video_path}: {e}") from e

        if keypoints.size == 0 or keypoints.shape[0] < 2:
            if skip_missing:
                continue
            raise ValueError(f"Too few frames for {video_path}")

        seq = preprocess_sequence(
            keypoints,
            target_length=target_length,
            center=True,
            scale=True,
            augment_flip=False,
            augment_temporal_crop=False,
        )
        templates_list.append(seq)
        meta_list.append({
            "exercise_id": ex_id,
            "exercise_name": ex.get("exerciseName", ""),
        })

    if not templates_list:
        raise ValueError("No templates built; no valid videos found.")

    templates = np.stack(templates_list, axis=0)
    np.savez_compressed(
        out_dir / "templates.npz",
        templates=templates,
    )
    with open(out_dir / "templates_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_list, f, indent=2)
    return len(templates_list)


def load_templates(templates_dir: str | Path) -> tuple[np.ndarray, list[dict]]:
    """Load templates array (N, T, V, C) and meta list of {exercise_id, exercise_name} per index."""
    templates_dir = Path(templates_dir)
    data = np.load(templates_dir / "templates.npz", allow_pickle=False)
    templates = data["templates"]
    with open(templates_dir / "templates_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    assert len(meta) == len(templates), "templates_meta.json length mismatch"
    return templates, meta


def match_video(
    video_path: str | Path,
    templates_dir: str | Path,
    target_length: int = 64,
    top_k: int = 5,
    use_fastdtw: bool = True,
) -> list[tuple[str, str, float]]:
    """
    Match a video to the nearest exercises by DTW. Returns list of (exercise_id, exercise_name, distance).
    When multiple templates belong to the same exercise, uses min distance to that exercise.
    """
    templates_dir = Path(templates_dir)
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    keypoints = extract_keypoints_from_video(video_path, use_visibility=True)
    if keypoints.size == 0 or keypoints.shape[0] < 2:
        return []

    query = preprocess_sequence(
        keypoints,
        target_length=target_length,
        center=True,
        scale=True,
        augment_flip=False,
        augment_temporal_crop=False,
    )

    templates, meta = load_templates(templates_dir)
    return _match_query_to_templates(query, templates, meta, top_k, use_fastdtw)


def _match_query_to_templates(
    query: np.ndarray,
    templates: np.ndarray,
    meta: list[dict],
    top_k: int,
    use_fastdtw: bool = True,
) -> list[tuple[str, str, float]]:
    """Match a preprocessed query (T, V, C) to loaded templates. Returns list of (exercise_id, exercise_name, distance)."""
    distances = [dtw_distance(query, templates[i], use_fastdtw=use_fastdtw) for i in range(len(templates))]
    exercise_best: dict[str, tuple[str, float]] = {}
    for i, m in enumerate(meta):
        eid = m["exercise_id"]
        name = m.get("exercise_name", "")
        d = distances[i]
        if eid not in exercise_best or d < exercise_best[eid][1]:
            exercise_best[eid] = (name, d)
    sorted_exercises = sorted(exercise_best.items(), key=lambda x: x[1][1])
    return [(eid, name, dist) for eid, (name, dist) in sorted_exercises[:top_k]]


def match_keypoints(
    keypoints: np.ndarray,
    templates_dir: str | Path,
    target_length: int = 64,
    top_k: int = 5,
    use_fastdtw: bool = True,
) -> list[tuple[str, str, float]]:
    """
    Match pre-extracted keypoints (T, V, C) to the template database.
    Same as match_video but accepts keypoint array instead of video path. Use for live streams.
    """
    if keypoints.size == 0 or keypoints.shape[0] < 2:
        return []
    query = preprocess_sequence(
        keypoints,
        target_length=target_length,
        center=True,
        scale=True,
        augment_flip=False,
        augment_temporal_crop=False,
    )
    templates, meta = load_templates(templates_dir)
    return _match_query_to_templates(query, templates, meta, top_k, use_fastdtw)


def main():
    parser = argparse.ArgumentParser(description="DTW-based exercise matcher: build templates or match a video")
    parser.add_argument("--build-templates", action="store_true", help="Build template store from exercises.json")
    parser.add_argument("--data-dir", type=str, default="data", help="Base directory for videoPathLocal (and exercises.json if --exercises-json is relative)")
    parser.add_argument("--exercises-json", type=str, default="data/exercises.json", help="Path to exercises.json")
    parser.add_argument("--out-dir", type=str, default="data/dtw_templates", help="Directory for templates.npz and templates_meta.json")
    parser.add_argument("--target-length", type=int, default=64)
    parser.add_argument("--max-videos", type=int, default=None, help="Max number of videos to use when building templates (default: all)")
    parser.add_argument("--video", type=str, default=None, help="Video path to match (when not building templates)")
    parser.add_argument("--templates", type=str, default="data/dtw_templates", help="Templates directory for matching")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=str, default=None, help="Write match results to JSON")
    args = parser.parse_args()

    if args.build_templates:
        exercises_path = Path(args.exercises_json)
        if not exercises_path.is_file():
            exercises_path = Path(args.data_dir) / "exercises.json"
        if not exercises_path.is_file():
            raise SystemExit(f"Exercises JSON not found: {args.exercises_json}")
        n = build_templates(
            data_dir=args.data_dir,
            exercises_json_path=exercises_path,
            out_dir=args.out_dir,
            target_length=args.target_length,
            skip_missing=True,
            max_videos=args.max_videos,
        )
        print(f"Built {n} templates in {args.out_dir}")
        return

    if args.video is None:
        parser.error("Either --build-templates or --video must be provided")
    results = match_video(
        args.video,
        args.templates,
        target_length=args.target_length,
        top_k=args.top_k,
    )
    for eid, name, dist in results:
        print(f"  {eid}  {name}  distance={dist:.2f}")
    if args.output:
        out = [{"exercise_id": eid, "exercise_name": name, "distance": dist} for eid, name, dist in results]
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
