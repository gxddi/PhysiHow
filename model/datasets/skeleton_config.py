"""
Canonical skeleton layout and graph structure for MediaPipe Pose (33 landmarks).
Used for keypoint extraction, preprocessing, and ST-GCN adjacency.
"""
import numpy as np

# MediaPipe Pose landmark indices (33 points)
# https://developers.google.com/mediapipe/solutions/vision/pose_landmarker
MEDIAPIPE_POSE_LANDMARKS = [
    "nose",           # 0
    "left_eye_inner", # 1
    "left_eye",       # 2
    "left_eye_outer", # 3
    "right_eye_inner",# 4
    "right_eye",      # 5
    "right_eye_outer",# 6
    "left_ear",       # 7
    "right_ear",      # 8
    "mouth_left",     # 9
    "mouth_right",    # 10
    "left_shoulder",  # 11
    "right_shoulder", # 12
    "left_elbow",     # 13
    "right_elbow",    # 14
    "left_wrist",     # 15
    "right_wrist",    # 16
    "left_pinky",     # 17
    "right_pinky",    # 18
    "left_index",     # 19
    "right_index",    # 20
    "left_thumb",     # 21
    "right_thumb",    # 22
    "left_hip",       # 23
    "right_hip",      # 24
    "left_knee",      # 25
    "right_knee",     # 26
    "left_ankle",     # 27
    "right_ankle",    # 28
    "left_heel",      # 29
    "right_heel",     # 30
    "left_foot_index",# 31
    "right_foot_index",# 32
]

NUM_JOINTS = len(MEDIAPIPE_POSE_LANDMARKS)  # 33

# Undirected edges (each pair stored once; adjacency is symmetric)
# Format: (parent, child) following body topology
MEDIAPIPE_EDGES = [
    (0, 1), (1, 2), (2, 3), (0, 4), (4, 5), (5, 6), (0, 7), (0, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31),
    (24, 26), (26, 28), (28, 30), (28, 32),
]

# Build adjacency list and matrix for ST-GCN
def get_adjacency_matrix():
    A = np.zeros((NUM_JOINTS, NUM_JOINTS), dtype=np.float32)
    for i, j in MEDIAPIPE_EDGES:
        A[i, j] = 1
        A[j, i] = 1
    return A

def get_adjacency_list():
    adj = [[] for _ in range(NUM_JOINTS)]
    for i, j in MEDIAPIPE_EDGES:
        adj[i].append(j)
        adj[j].append(i)
    return adj

ADJACENCY_MATRIX = get_adjacency_matrix()
ADJACENCY_LIST = get_adjacency_list()

# Indices of joints used for centering (mid-hip)
HIP_INDICES = (23, 24)

# Number of coordinate channels: x, y, z (or x, y, visibility)
NUM_COORD_CHANNELS = 3
