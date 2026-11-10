"""Employee identification by face.

Photos of employees live in FACES_DIR, one folder per employee named "<employee_id>_<name>", e.g.
    faces/12_Aigul/1.jpg, faces/12_Aigul/2.jpg
employee_id must match the id of the employee in the backend. 3-5 photos per person (front, slight turns,
with/without glasses) work noticeably better than one. Photos never leave this machine: only the resulting
employee_id is sent to the backend.

Uses OpenCV's built-in YuNet (detector) and SFace (recogniser), so no extra Python packages are needed.
"""
import os
import threading
import time
import urllib.request
from typing import Optional

import cv2
import numpy as np

MODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

FACES_DIR = os.getenv("FACES_DIR", os.path.join(MODULE_DIR, "faces"))
FACE_DET_MODEL = os.getenv("FACE_DET_MODEL", os.path.join(MODULE_DIR, "face_detection_yunet_2023mar.onnx"))
FACE_REC_MODEL = os.getenv("FACE_REC_MODEL", os.path.join(MODULE_DIR, "face_recognition_sface_2021dec.onnx"))
_MODEL_URLS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

FACE_DET_SCORE = float(os.getenv("FACE_DET_SCORE", "0.8"))
# Faces narrower than this (px in the original frame) are too blurry to identify anyone reliably.
FACE_MIN_SIZE = int(os.getenv("FACE_MIN_SIZE", "40"))
# Cosine similarity of SFace features. OpenCV's reference threshold for "same person" is 0.363.
FACE_MATCH_THRESH = float(os.getenv("FACE_MATCH_THRESH", "0.40"))
# The best employee must beat the runner-up by this much, otherwise the frame doesn't vote.
FACE_MATCH_MARGIN = float(os.getenv("FACE_MATCH_MARGIN", "0.05"))
# A person becomes an employee after this many frames agree on them (one frame can be a fluke).
FACE_VOTES = int(os.getenv("FACE_VOTES", "2"))
FACE_RELOAD_SEC = float(os.getenv("FACE_RELOAD_SEC", "30"))
# Where a person's own face may be inside their box (fractions of box width/height, see find_face).
FACE_CENTER_MIN, FACE_CENTER_MAX = 0.2, 0.8
FACE_MAX_TOP = 0.3
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def ensure_models():
    for path in (FACE_DET_MODEL, FACE_REC_MODEL):
        if os.path.isfile(path):
            continue
        url = _MODEL_URLS.get(os.path.basename(path))
        if url is None:
            raise FileNotFoundError(f"Face model not found: {path}")
        print(f"Downloading {os.path.basename(path)}...")
        tmp = path + ".part"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)


class FaceModels:
    """Detector + recogniser. Not thread-safe: every camera worker owns its own instance."""

    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(FACE_DET_MODEL, "", (320, 320), FACE_DET_SCORE, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(FACE_REC_MODEL, "")

    def detect(self, image):
        """Returns YuNet rows [x, y, w, h, 5 landmarks (10 values), score], largest face first."""
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)
        if faces is None:
            return []
        return sorted(faces, key=lambda f: -f[2] * f[3])

    def embed(self, image, face_row):
        aligned = self.recognizer.alignCrop(image, face_row)
        feat = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return feat / max(np.linalg.norm(feat), 1e-12)


class FaceGallery:
    """Embeddings of employee photos, shared by all cameras; reloaded when FACES_DIR changes."""

    def __init__(self, models: FaceModels):
        self.models = models
        self.lock = threading.Lock()
        self._reload_lock = threading.Lock()
        self.feats = np.zeros((0, 128), dtype=np.float32)
        self.owner = np.zeros(0, dtype=np.int64)   # employee_id of every row in feats
        self.names = {}                            # employee_id -> display name
        self._signature = None
        self._last_check = 0.0
        self.reload(force=True)

    def _scan(self):
        files = []
        if os.path.isdir(FACES_DIR):
            for entry in sorted(os.listdir(FACES_DIR)):
                folder = os.path.join(FACES_DIR, entry)
                if not os.path.isdir(folder):
                    continue
                for name in sorted(os.listdir(folder)):
                    if name.lower().endswith(_IMAGE_EXT):
                        path = os.path.join(folder, name)
                        files.append((entry, path, os.path.getmtime(path)))
        return files

    def reload(self, force=False):
        """Re-reads FACES_DIR if photos were added/changed. Called by camera threads; only one reloads at a time."""
        now = time.time()
        if not force and now - self._last_check < FACE_RELOAD_SEC:
            return
        if not self._reload_lock.acquire(blocking=False):
            return  # another camera is reloading right now
        try:
            self._last_check = now
            self._reload()
        finally:
            self._reload_lock.release()

    def _reload(self):
        files = self._scan()
        signature = tuple((p, m) for _, p, m in files)
        if signature == self._signature:
            return
        feats, owner, names = [], [], {}
        for folder, path, _ in files:
            id_part, _, name = folder.partition("_")
            if not id_part.isdigit():
                print(f"Faces: skipping folder '{folder}', expected '<employee_id>_<name>'")
                continue
            employee_id = int(id_part)
            names[employee_id] = name or f"#{employee_id}"
            image = cv2.imread(path)
            if image is None:
                print(f"Faces: cannot read {path}")
                continue
            # Big phone photos: the detector works on a downscaled copy, landmarks are scaled back.
            scale = min(1.0, 1280 / max(image.shape[:2]))
            if scale < 1.0:
                image = cv2.resize(image, None, fx=scale, fy=scale)
            faces = self.models.detect(image)
            if not faces:
                print(f"Faces: no face found on {path}")
                continue
            if len(faces) > 1:
                print(f"Faces: {len(faces)} faces on {path}, using the largest one")
            feats.append(self.models.embed(image, faces[0]))
            owner.append(employee_id)
        with self.lock:
            self.feats = np.stack(feats) if feats else np.zeros((0, 128), dtype=np.float32)
            self.owner = np.array(owner, dtype=np.int64)
            self.names = names
        self._signature = signature
        print(f"Faces: {len(feats)} photo(s) of {len(set(owner))} employee(s) loaded from {FACES_DIR}")

    def match(self, feat):
        """Returns (employee_id, similarity) if the face clearly belongs to one employee, else (None, best_sim)."""
        with self.lock:
            feats, owner = self.feats, self.owner
        if len(owner) == 0:
            return None, -1.0
        sims = feats @ feat
        best = {}  # best photo per employee
        for employee_id, sim in zip(owner.tolist(), sims.tolist()):
            best[employee_id] = max(sim, best.get(employee_id, -1.0))
        ranked = sorted(best.items(), key=lambda x: -x[1])
        employee_id, sim = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        if sim >= FACE_MATCH_THRESH and sim - second >= FACE_MATCH_MARGIN:
            return employee_id, sim
        return None, sim

    def name(self, employee_id: int):
        return self.names.get(employee_id, f"#{employee_id}")

    def __len__(self):
        return len(self.owner)


def find_face(models: FaceModels, frame, box) -> Optional[np.ndarray]:
    """Looks for a face in the head region of a person box. Returns its embedding or None."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    bw, bh = x2 - x1, y2 - y1
    if bw < FACE_MIN_SIZE:
        return None
    # The head is in the upper part of the box; when only the upper body is visible the box is short and
    # the face can be lower, so take more of it.
    head_h = int(bh * (0.45 if bh > 2.2 * bw else 0.8))
    pad = int(bw * 0.15)
    cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
    cx2, cy2 = min(w, x2 + pad), min(h, y1 + head_h)
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0 or crop.shape[0] < FACE_MIN_SIZE or crop.shape[1] < FACE_MIN_SIZE:
        return None
    # The crop often also contains the face of someone standing behind or next to this person. A face only
    # counts if it sits where this person's head is: horizontally around the middle of the box and at its top.
    # On test footage every wrong identification came from such a face (at the box edge or halfway down it).
    for face in models.detect(crop):
        fx, fy, fw = face[0] + cx1, face[1] + cy1, face[2]
        if fw < FACE_MIN_SIZE:
            break  # sorted by size: the rest are even smaller
        center_x = (fx + fw / 2 - x1) / bw
        top = (fy - y1) / bh
        if FACE_CENTER_MIN <= center_x <= FACE_CENTER_MAX and top <= FACE_MAX_TOP:
            return models.embed(crop, face)
    return None
