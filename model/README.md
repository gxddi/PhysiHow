# Exercise matching pipeline (DTW)

Match a new exercise video (or live webcam) to the closest exercise in your dataset using **skeleton keypoints** and **Dynamic Time Warping**. No training.

---

## How the pipeline works

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  OFFICE (once)                                                               │
│  exercises.json + video files                                                │
│         │                                                                    │
│         ▼                                                                    │
│  For each exercise:  video → MediaPipe Pose → keypoints (T, 33, 4)         │
│         │                                                                    │
│         ▼                                                                    │
│  Preprocess:  resample to 64 frames, center on hip, scale by torso          │
│         │                                                                    │
│         ▼                                                                    │
│  Save as  templates.npz  +  templates_meta.json                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  MATCH (new video or webcam)                                                 │
│  New video / live frames                                                     │
│         │                                                                    │
│         ▼                                                                    │
│  MediaPipe Pose → keypoints  →  same preprocessing (64 frames, center, scale)│
│         │                                                                    │
│         ▼                                                                    │
│  DTW distance between this sequence and every template                      │
│         │                                                                    │
│         ▼                                                                    │
│  Return top-k exercises with smallest distance (lower = more similar)       │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Steps in code:**

1. **Skeleton** – MediaPipe Pose gives 33 body landmarks per frame (x, y, z, visibility). Stored as arrays of shape `(T, 33, 4)` (T = time/frames).
2. **Preprocess** – All sequences are resampled to the same length (e.g. 64 frames), centered on the hip, and scaled by torso length so pose size and position don’t dominate the distance.
3. **DTW** – For a query sequence and each template, Dynamic Time Warping computes a single distance (Euclidean cost, time-warped). The template with the smallest distance is the best match.
4. **Templates** – Built once from your exercises JSON (one template per exercise video). Matching is then “query vs every template” and return the nearest.

---

## Data you need

- **Exercises JSON** – One JSON file with an `"exercises"` array. Each item: `id`, `videoPathLocal` (path to video relative to data dir), and optionally `exerciseName`.
- **Videos** – In a folder (e.g. `data/`); paths in the JSON are relative to that folder.

---

## Commands (run from project root)

**1. Build templates (once)**  
Creates `data/dtw_templates/templates.npz` and `templates_meta.json`.

```bash
python -m model.inference.dtw_match --build-templates --data-dir data --exercises-json data/exercises.json --out-dir data/dtw_templates
```

**2. Match a video file**

```bash
python -m model.inference.dtw_match --video path/to/video.mp4 --templates data/dtw_templates --top-k 5
```

**3. Live webcam**  
Shows pose overlay and top-k matches; press **q** to quit.

```bash
python -m model.inference.webcam_demo --templates data/dtw_templates --top-k 3
```

---

## What’s in this repo

| Path | Purpose |
|------|--------|
| `model/datasets/skeleton_config.py` | 33-joint layout and body graph (used by preprocessing). |
| `model/datasets/keypoint_extraction.py` | Run MediaPipe on a video (or single frame) → keypoints. |
| `model/datasets/preprocessing.py` | Resample to fixed length, center, scale. |
| `model/inference/dtw_match.py` | Build templates from JSON + match a video (CLI). |
| `model/inference/webcam_demo.py` | Webcam capture, buffer keypoints, match every N frames. |

Dependencies: `model/requirements.txt` (numpy, scipy, mediapipe, opencv-python, tqdm, fastdtw).
