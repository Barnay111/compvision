import itertools
import json
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

# RTSP over TCP: UDP drops packets on busy networks and the picture "smears". Must be set before cv2 opens a stream.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np
import requests
from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify
from ultralytics import YOLO
from ultralytics.trackers.utils.reid import ReID, smooth_feature

load_dotenv()

import faces as face_id  # noqa: E402  (reads its settings from the environment, so after load_dotenv)

MODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Configuration
API_URL = os.getenv("API_URL", "http://127.0.0.1:8002")
BRANCH_ID = int(os.getenv("BRANCH_ID", "1"))
# Cameras are listed in CAMERAS_FILE (see cameras.example.json). Without it a single camera RTSP_URL is used.
CAMERAS_FILE = os.getenv("CAMERAS_FILE", os.path.join(MODULE_DIR, "cameras.json"))
RTSP_URL = os.getenv("RTSP_URL", "0")  # 0 for webcam
STREAM_PORT = int(os.getenv("STREAM_PORT", "5002"))
MODEL_PATH = os.getenv("MODEL_PATH", "yolo26s.pt")
# Detector input size. 640 is enough when people are large in the frame; 960 helps wide-angle cameras with
# distant people (~+2-5% detections on test footage) at ~2x the compute. Can be overridden per camera.
IMG_SIZE = int(os.getenv("IMG_SIZE", "640"))
DETECT_CONF = float(os.getenv("DETECT_CONF", "0.25"))
TRACKER_CONFIG = os.getenv("TRACKER_CONFIG", os.path.join(MODULE_DIR, "trackers", "botsort_cctv.yaml"))
SHOW_WINDOW = os.getenv("SHOW_WINDOW", "1") == "1"

# Live streams: reconnect with exponential backoff up to this many seconds between attempts.
RECONNECT_MAX_SEC = float(os.getenv("RECONNECT_MAX_SEC", "30"))
# How long a hung stream may block open()/read() before we treat it as lost.
STREAM_TIMEOUT_MS = int(os.getenv("STREAM_TIMEOUT_MS", "10000"))

# Line crossing settings (LINE_Y is the default for cameras that don't set their own line_y)
LINE_Y = int(os.getenv("LINE_Y", "300"))
# Which point of a person is compared with the line: "bottom" (feet) matches where the line is drawn on the floor;
# "center" is the box centre, which for tall boxes near the camera sits far above the feet.
LINE_ANCHOR = os.getenv("LINE_ANCHOR", "bottom")
# Hysteresis: a person must move this many px past the line to count as being on the other side.
LINE_MARGIN = int(os.getenv("LINE_MARGIN", "15"))
# Minimum seconds between two events of the same track (suppresses jitter).
EVENT_COOLDOWN = float(os.getenv("EVENT_COOLDOWN", "2.0"))
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "3.0"))
STREAM_MAX_FPS = float(os.getenv("STREAM_MAX_FPS", "25"))

# ReID: recognise a person who left and came back (smoke break, phone call) by appearance only.
# Embeddings live in RAM only and are dropped after REID_TTL_MIN; nothing is stored or sent to the API.
REID_MODEL = os.getenv("REID_MODEL", "yolo26n-reid.onnx")
REID_TTL_MIN = float(os.getenv("REID_TTL_MIN", "30"))
# "minutes:min_similarity" steps — the longer someone was away, the more similar they must look.
# Calibrated on test footage with yolo26n-reid: at 0.60 ~40% of returning people are recognised and ~6% of
# matches pick the wrong person (a new visitor counted as returning). The old 0.70+ practically never matched.
REID_THRESHOLDS = os.getenv("REID_THRESHOLDS", "5:0.60,15:0.63,30:0.66")
# The best gallery match must beat the second best by this much, otherwise it is ambiguous and ignored.
REID_MARGIN = float(os.getenv("REID_MARGIN", "0.05"))
# Single-frame embeddings are too noisy to identify anyone (same person ~0.41 vs. others ~0.39 on test footage);
# an average of a few clean frames is needed before a person is matched against or added to the gallery.
REID_MIN_SAMPLES = int(os.getenv("REID_MIN_SAMPLES", "3"))
REID_EVERY_N_FRAMES = int(os.getenv("REID_EVERY_N_FRAMES", "5"))
# Quality gate for embeddings: crops of people partly hidden by someone else, cut by the frame edge or detected
# with low confidence describe the wrong thing and spoil the running average. Skipping them raised correct
# return matches on test footage from 43% to 93% (rank-1 among 7 people).
REID_MIN_BOX_H = int(os.getenv("REID_MIN_BOX_H", "80"))  # smaller crops give unreliable embeddings
REID_MIN_CONF = float(os.getenv("REID_MIN_CONF", "0.5"))
REID_MAX_OVERLAP = float(os.getenv("REID_MAX_OVERLAP", "0.3"))  # share of the box covered by another person's box
REID_BORDER_PX = int(os.getenv("REID_BORDER_PX", "4"))
REID_EMA = float(os.getenv("REID_EMA", "0.9"))  # weight of the running average vs. the newest embedding
# Track stitching: when the tracker loses someone (occlusion, missed detections) and starts a new track,
# the new track inherits the ID of a person who vanished within REID_STITCH_SEC and looks similar enough.
REID_STITCH_SEC = float(os.getenv("REID_STITCH_SEC", "10"))
REID_STITCH_THRESH = float(os.getenv("REID_STITCH_THRESH", "0.72"))
PERSON_FORGET_SEC = 120.0  # drop state of people not seen this long

# Employee identification by face (see faces.py). Can be switched off per camera with "faces": false.
FACES_ENABLED = os.getenv("FACES_ENABLED", "1") == "1"
FACE_EVERY_N_FRAMES = int(os.getenv("FACE_EVERY_N_FRAMES", "3"))  # how often unidentified people are checked


@dataclass
class CameraConfig:
    id: str
    url: str
    name: str
    branch_id: int
    line_y: int
    enter_side: str  # "below" or "above": the side of the line that is "inside" (entering = crossing into it)
    anchor: str = LINE_ANCHOR  # "bottom" (feet) or "center"
    imgsz: int = IMG_SIZE
    faces: bool = True  # identify employees by face on this camera


def _resolve_url(url: str):
    """Relative video file paths are looked up next to cv_module, so the cwd doesn't matter."""
    if "://" in url or url.isdigit() or os.path.isabs(url) or os.path.isfile(url):
        return url
    candidate = os.path.join(MODULE_DIR, url)
    return os.path.normpath(candidate) if os.path.isfile(candidate) else url


def load_cameras():
    if not os.path.isfile(CAMERAS_FILE):
        return [CameraConfig(id="cam1", url=RTSP_URL, name="Camera 1", branch_id=BRANCH_ID,
                             line_y=LINE_Y, enter_side="below")]
    with open(CAMERAS_FILE) as f:
        raw = json.load(f)
    cameras = []
    for i, c in enumerate(raw, 1):
        if c.get("enabled", True) is False:
            continue
        enter_side = c.get("enter_side", "below")
        if enter_side not in ("below", "above"):
            raise ValueError(f"camera {c.get('id')}: enter_side must be 'below' or 'above'")
        anchor = c.get("anchor", LINE_ANCHOR)
        if anchor not in ("bottom", "center"):
            raise ValueError(f"camera {c.get('id')}: anchor must be 'bottom' or 'center'")
        cameras.append(CameraConfig(
            id=str(c.get("id", f"cam{i}")),
            # ${VAR} lets passwords stay in .env instead of the cameras file.
            url=_resolve_url(os.path.expandvars(str(c["url"]))),
            name=c.get("name", f"Camera {i}"),
            branch_id=int(c.get("branch_id", BRANCH_ID)),
            line_y=int(c.get("line_y", LINE_Y)),
            enter_side=enter_side,
            anchor=anchor,
            imgsz=int(c.get("imgsz", IMG_SIZE)),
            faces=bool(c.get("faces", True)),
        ))
    ids = [c.id for c in cameras]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate camera ids in {CAMERAS_FILE}: {ids}")
    if not cameras:
        raise ValueError(f"no enabled cameras in {CAMERAS_FILE}")
    return cameras


def _mask_url(url: str):
    """Hides the password in rtsp://user:pass@host URLs for logs."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        return f"{scheme}://{creds.split(':', 1)[0]}:***@{host}"
    return url


def _parse_thresholds(spec: str):
    steps = []
    for part in spec.split(","):
        minutes, sim = part.split(":")
        steps.append((float(minutes) * 60, float(sim)))
    return sorted(steps)


class ReturnGallery:
    """Short-lived memory of people who recently exited, used to recognise them on re-entry.

    Shared by all cameras of the process, so someone leaving through one door and coming back
    through another is still recognised. Thread-safe.
    """

    def __init__(self, ttl_sec: float, thresholds):
        self.ttl_sec = ttl_sec
        self.thresholds = thresholds
        self.entries = {}  # visitor_id -> (embedding, exit_time)
        self.lock = threading.Lock()

    def _threshold(self, away_sec: float):
        for max_away, sim in self.thresholds:
            if away_sec <= max_away:
                return sim
        return None  # away longer than the last step -> treat as a new visit

    def _prune(self, now: float):
        self.entries = {v: e for v, e in self.entries.items() if now - e[1] <= self.ttl_sec}

    def prune(self, now: float):
        with self.lock:
            self._prune(now)

    def add(self, visitor_id: int, embedding: np.ndarray, now: float):
        with self.lock:
            self.entries[visitor_id] = (embedding, now)

    def match(self, embedding: np.ndarray, now: float):
        """Returns (visitor_id, similarity) of the best match above its time-based threshold, else (None, best_sim)."""
        with self.lock:
            self._prune(now)
            scored = []
            for visitor_id, (emb, exit_time) in self.entries.items():
                scored.append((float(np.dot(embedding, emb)), visitor_id, exit_time))
            if not scored:
                return None, -1.0
            scored.sort(reverse=True)
            best_sim, best_id, exit_time = scored[0]
            second_sim = scored[1][0] if len(scored) > 1 else -1.0
            threshold = self._threshold(now - exit_time)
            # Only the overall best match may be accepted: if it is too close to the runner-up the two people
            # look alike and picking either would be a guess.
            if threshold is None or best_sim < threshold or best_sim - second_sim < REID_MARGIN:
                return None, best_sim
            del self.entries[best_id]  # one exit can be matched by one entry only
            return best_id, best_sim


gallery = ReturnGallery(REID_TTL_MIN * 60, _parse_thresholds(REID_THRESHOLDS))

# Person ids must never repeat: two cameras must not report different people under the same id, and neither may
# a restarted process (the backend links employees to events by person_id). Counting from the start time in ms
# guarantees that as long as fewer than 1000 people per second appear. On screen only the last 4 digits are shown.
_pid_counter = itertools.count(int(time.time() * 1000))
_pid_lock = threading.Lock()


def next_person_id():
    with _pid_lock:
        return next(_pid_counter)


# Events are sent in the background so a slow API never stalls video processing.
_event_executor = ThreadPoolExecutor(max_workers=4)


def _post_event(payload: dict, tag: str):
    try:
        response = requests.post(f"{API_URL}/events/", json=payload, timeout=API_TIMEOUT)
        response.raise_for_status()
        print(f"{tag} Event sent successfully: {payload}")
    except requests.exceptions.RequestException as e:
        print(f"{tag} Failed to send event to API: {e}")


def send_event(camera: CameraConfig, person_id: int, action: str, returning: bool = False,
               employee_id: Optional[int] = None):
    """Queues an event ("ENTER" or "EXIT") for the backend API.

    person_id is an anonymous visitor id that survives a short exit/re-entry (see ReID),
    so counting distinct person_id values gives the number of visits.
    employee_id is set when the person was recognised as an employee by face.
    """
    payload = {
        "branch_id": camera.branch_id,
        "person_id": person_id,
        "action": action,
        "timestamp": time.time(),
        "returning": returning,
        "employee_id": employee_id,
    }
    _event_executor.submit(_post_event, payload, f"[{camera.id}]")


def _post_identify(payload: dict, tag: str):
    try:
        response = requests.post(f"{API_URL}/events/identify", json=payload, timeout=API_TIMEOUT)
        response.raise_for_status()
        print(f"{tag} Identified: {payload} -> {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"{tag} Failed to send identification to API: {e}")


def send_identify(camera: CameraConfig, person_id: int, employee_id: int):
    """Tells the backend that person_id is an employee, so events sent before the face was seen get linked too."""
    payload = {"branch_id": camera.branch_id, "person_id": person_id, "employee_id": employee_id}
    _event_executor.submit(_post_identify, payload, f"[{camera.id}]")


class FrameHub:
    """Latest annotated frame of one camera, shared with MJPEG clients and the preview window."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg = None
        self.frame = None
        self.seq = 0

    def publish(self, frame):
        ok, buffer = cv2.imencode('.jpg', frame)
        if not ok:
            return
        with self.cond:
            self.frame = frame
            self.jpeg = buffer.tobytes()
            self.seq += 1
            self.cond.notify_all()

    def mjpeg(self):
        last_seq = 0
        min_interval = 1.0 / STREAM_MAX_FPS if STREAM_MAX_FPS > 0 else 0
        last_sent = 0.0
        while True:
            with self.cond:
                # Wait for a frame newer than the one already sent to this client.
                self.cond.wait_for(lambda: self.seq != last_seq, timeout=1.0)
                if self.seq == last_seq or self.jpeg is None:
                    continue
                last_seq = self.seq
                jpeg = self.jpeg

            wait = min_interval - (time.time() - last_sent)
            if wait > 0:
                time.sleep(wait)
            last_sent = time.time()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')


class VideoSource:
    """Reads frames from a camera, a webcam index or a video file.

    Live sources are read in a background thread that keeps only the newest frame (so a slow detector
    never lags behind real time) and reconnects with backoff when the stream drops.
    Files are read sequentially, frame by frame, and end at EOF.
    """

    def __init__(self, url: str, tag: str):
        self.url = url
        self.tag = tag
        self.is_file = os.path.isfile(url)
        self.online = False
        self.stopped = threading.Event()
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._cap = None
        if self.is_file:
            self._cap = cv2.VideoCapture(url)
            self.online = self._cap.isOpened()
        else:
            threading.Thread(target=self._reader, name=f"reader-{tag}", daemon=True).start()

    def _open(self):
        if self.url.isdigit():
            return cv2.VideoCapture(int(self.url))
        return cv2.VideoCapture(self.url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, STREAM_TIMEOUT_MS,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, STREAM_TIMEOUT_MS,
        ])

    def _reader(self):
        delay = 1.0
        while not self.stopped.is_set():
            cap = self._open()
            if not cap.isOpened():
                cap.release()
                print(f"{self.tag} Cannot open {_mask_url(self.url)}, retrying in {delay:.0f}s")
                self.stopped.wait(delay)
                delay = min(delay * 2, RECONNECT_MAX_SEC)
                continue
            print(f"{self.tag} Connected to {_mask_url(self.url)}")
            self.online = True
            delay = 1.0
            while not self.stopped.is_set():
                ok, frame = cap.read()
                if not ok:
                    print(f"{self.tag} Stream lost, reconnecting...")
                    break
                with self._cond:
                    self._frame = frame
                    self._seq += 1
                    self._cond.notify_all()
            self.online = False
            cap.release()

    def read(self, last_seq: int):
        """Returns (seq, frame) of a frame newer than last_seq, or (last_seq, None) if none is ready yet
        (live source waiting for reconnect). Returns (None, None) when the source has ended."""
        if self.stopped.is_set():
            return None, None
        if self.is_file:
            ok, frame = self._cap.read()
            if not ok:
                return None, None
            return last_seq + 1, frame
        with self._cond:
            self._cond.wait_for(lambda: self._seq != last_seq or self.stopped.is_set(), timeout=1.0)
            if self._seq == last_seq:
                return last_seq, None
            return self._seq, self._frame

    def release(self):
        self.stopped.set()
        self.online = False
        if self._cap is not None:
            self._cap.release()


@dataclass
class Person:
    """A person as we see them, independent of the tracker's (unstable) track ids."""
    pid: int                              # stable anonymous id: shown on video and sent to the API
    last_seen: float
    feat: Optional[np.ndarray] = None     # smoothed appearance embedding (RAM only)
    feat_n: int = 0                       # number of clean embeddings averaged into feat
    side: Optional[str] = None            # last confirmed side of the line
    last_event: float = 0.0
    has_event: bool = False
    returning: bool = False
    work_total: float = 0.0
    work_since: Optional[float] = None
    employee_id: Optional[int] = None     # set once the face was recognised as an employee
    face_votes: dict = field(default_factory=dict)  # employee_id -> frames where the face matched them

    def update_feat(self, feat):
        if feat is not None:
            _, self.feat = smooth_feature(feat, self.feat, REID_EMA)
            self.feat_n += 1

    @property
    def reliable_feat(self):
        """The appearance embedding if it is averaged over enough clean frames to identify the person."""
        return self.feat if self.feat_n >= REID_MIN_SAMPLES else None


class PersonRegistry:
    """Maps tracker ids of one camera to stable people and stitches broken tracks back together by appearance."""

    def __init__(self, tag: str):
        self.tag = tag
        self.people = {}       # pid -> Person
        self.by_track = {}     # tracker id -> Person
        self.created = 0
        self.tracker_ids_seen = set()

    def _new_person(self, now):
        person = Person(pid=next_person_id(), last_seen=now)
        self.created += 1
        self.people[person.pid] = person
        return person

    def resolve(self, track_ids, feats, now):
        """Returns a Person for every visible track. `feats` holds embeddings for (at least) new tracks."""
        self.tracker_ids_seen.update(track_ids)
        visible = {self.by_track[t].pid for t in track_ids if t in self.by_track}
        new_tracks = [i for i, t in enumerate(track_ids) if t not in self.by_track]

        # Candidates for stitching: people who vanished recently and are not on screen now.
        lost = [
            p for p in self.people.values()
            if p.pid not in visible and p.feat is not None and now - p.last_seen <= REID_STITCH_SEC
        ]
        pairs = []
        for i in new_tracks:
            if feats[i] is None:
                continue
            for p in lost:
                sim = float(np.dot(feats[i], p.feat))
                if sim >= REID_STITCH_THRESH:
                    pairs.append((sim, i, p))
        claimed_tracks, claimed_people = set(), set()
        for sim, i, p in sorted(pairs, key=lambda x: -x[0]):  # greedy: most similar pairs first
            if i in claimed_tracks or p.pid in claimed_people:
                continue
            claimed_tracks.add(i)
            claimed_people.add(p.pid)
            # Forget the old track id so it can't come back as a second copy of this person.
            for t in [t for t, q in self.by_track.items() if q is p]:
                del self.by_track[t]
            self.by_track[track_ids[i]] = p
            print(f"{self.tag} ReID: track {track_ids[i]} continues person {p.pid} (sim={sim:.2f})")

        for i in new_tracks:
            if i not in claimed_tracks:
                self.by_track[track_ids[i]] = self._new_person(now)

        people = [self.by_track[t] for t in track_ids]
        for person, feat in zip(people, feats):
            person.last_seen = now
            person.update_feat(feat)
        return people

    def rename(self, person, new_pid):
        """Gives a person the id of a returning visitor."""
        old = self.people.get(new_pid)
        if old is not None and old is not person:
            self.by_track = {t: p for t, p in self.by_track.items() if p is not old}
        self.people.pop(person.pid, None)
        person.pid = new_pid
        self.people[new_pid] = person

    def prune(self, now):
        stale = {pid for pid, p in self.people.items() if now - p.last_seen > PERSON_FORGET_SEC}
        for pid in stale:
            del self.people[pid]
        self.by_track = {t: p for t, p in self.by_track.items() if p.pid not in stale}


def draw_person(frame, box, person, now, employee_name=None):
    x1, y1, x2, y2 = map(int, box)
    working = person.work_since is not None
    color = (0, 200, 0) if working else (0, 0, 230)
    worked = person.work_total + (now - person.work_since if working else 0)
    if employee_name is not None:
        label = f"STAFF {employee_name}"
        color = (230, 140, 0) if working else (150, 90, 0)  # blue: employees
    else:
        label = f"ID {person.pid % 10000:04d}" + (" RETURN" if person.returning else "")
    status = f"{'WORKING' if working else 'IDLE'} | Work: {int(worked)}s"
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
    cv2.putText(frame, label, (x1 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, status, (x1, y2 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_offline(hub: FrameHub, camera: CameraConfig):
    """Shows a placeholder instead of a frozen last frame while the camera is reconnecting."""
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(frame, f"{camera.name}: NO SIGNAL", (30, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 230), 2)
    cv2.putText(frame, "reconnecting...", (30, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
    hub.publish(frame)


class CameraWorker(threading.Thread):
    """Detection, tracking and line counting for one camera, in its own thread.

    Each camera has its own YOLO model and ReID encoder: the tracker state lives inside the model
    (persist=True), so sharing one model between cameras would mix up their tracks.
    """

    def __init__(self, camera: CameraConfig, face_gallery: Optional["face_id.FaceGallery"] = None):
        super().__init__(name=f"camera-{camera.id}", daemon=True)
        self.camera = camera
        self.tag = f"[{camera.id}]"
        self.hub = FrameHub()
        self.source = None
        self.model = YOLO(MODEL_PATH)
        self.reid = ReID(REID_MODEL)
        self.face_gallery = face_gallery if camera.faces else None
        self.face_models = face_id.FaceModels() if self.face_gallery is not None else None
        self.registry = PersonRegistry(self.tag)
        self.stopped = threading.Event()

    @property
    def online(self):
        return self.source is not None and self.source.online

    def stop(self):
        self.stopped.set()
        if self.source is not None:
            self.source.stopped.set()  # the worker thread releases the capture itself (see run)

    def anchor_y(self, box):
        """The point of a person compared with the line: feet (box bottom) or box centre."""
        return int(box[3]) if self.camera.anchor == "bottom" else int((box[1] + box[3]) // 2)

    def side_of_line(self, y: int):
        """Returns 'inside', 'outside' or None while inside the dead zone around the line."""
        line_y = self.camera.line_y
        if y < line_y - LINE_MARGIN:
            side = "above"
        elif y > line_y + LINE_MARGIN:
            side = "below"
        else:
            return None
        return "inside" if side == self.camera.enter_side else "outside"

    def is_inside(self, y: int):
        """Work zone: the 'inside' half of the frame, without the hysteresis margin."""
        below = y > self.camera.line_y
        return below if self.camera.enter_side == "below" else not below

    @staticmethod
    def crop_quality(boxes, confs, frame_shape):
        """Returns two masks over boxes:
        - clean: the crop shows one whole, confidently detected person (for appearance ReID, see REID_MAX_OVERLAP);
        - alone: the box isn't covered by someone else, so a face found in it belongs to this person.
          Unlike `clean`, it allows boxes cut by the frame edge: people walking up to the camera are cut at the
          bottom exactly when their face is largest."""
        h, w = frame_shape[:2]
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        area = np.maximum((x2 - x1) * (y2 - y1), 1e-6)
        iw = np.clip(np.minimum(x2[:, None], x2[None]) - np.maximum(x1[:, None], x1[None]), 0, None)
        ih = np.clip(np.minimum(y2[:, None], y2[None]) - np.maximum(y1[:, None], y1[None]), 0, None)
        covered = iw * ih / area[:, None]  # [i, j]: share of box i covered by box j
        np.fill_diagonal(covered, 0)
        b = REID_BORDER_PX
        inside_frame = (x1 >= b) & (y1 >= b) & (x2 <= w - b) & (y2 <= h - b)
        alone = covered.max(axis=1, initial=0) <= REID_MAX_OVERLAP
        clean = (y2 - y1 >= REID_MIN_BOX_H) & (confs >= REID_MIN_CONF) & alone & inside_frame
        return clean, alone

    def identify_faces(self, frame, boxes, people, alone, frame_idx):
        """Looks for faces of not yet identified people and votes for the employee they match."""
        if self.face_gallery is None or len(self.face_gallery) == 0 or frame_idx % FACE_EVERY_N_FRAMES:
            return
        for box, person, ok in zip(boxes, people, alone):
            if person.employee_id is not None or not ok:
                continue
            feat = face_id.find_face(self.face_models, frame, box)
            if feat is None:
                continue
            employee_id, sim = self.face_gallery.match(feat)
            if employee_id is None:
                continue
            votes = person.face_votes
            votes[employee_id] = votes.get(employee_id, 0) + 1
            others = sum(v for e, v in votes.items() if e != employee_id)
            if votes[employee_id] >= face_id.FACE_VOTES and votes[employee_id] > 2 * others:
                person.employee_id = employee_id
                print(f"{self.tag} Face: person {person.pid} is employee {employee_id} "
                      f"'{self.face_gallery.name(employee_id)}' (sim={sim:.2f}, votes={votes})")
                send_identify(self.camera, person.pid, employee_id)

    def embed_boxes(self, frame, boxes_xyxy):
        """Returns one L2-normalised appearance embedding (or None) per xyxy box."""
        if len(boxes_xyxy) == 0:
            return []
        b = np.asarray(boxes_xyxy, dtype=np.float32)
        xywh = np.stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]],
                        axis=1)
        return self.reid(frame, xywh)

    def run(self):
        try:
            self._run()
        except Exception as e:  # one broken camera must not take the others down
            print(f"{self.tag} Worker crashed: {e!r}")
            raise
        finally:
            if self.source is not None:
                self.source.release()
            print(f"{self.tag} Stopped: tracker issued {len(self.registry.tracker_ids_seen)} track ids, "
                  f"shown as {self.registry.created} people after ReID stitching.")

    def _run(self):
        camera = self.camera
        print(f"{self.tag} Starting '{camera.name}': {_mask_url(camera.url)}, line_y={camera.line_y}, "
              f"enter_side={camera.enter_side}, anchor={camera.anchor}, imgsz={camera.imgsz}, "
              f"branch={camera.branch_id}")
        self.source = VideoSource(camera.url, self.tag)
        if self.source.is_file and not self.source.online:
            print(f"{self.tag} Error: could not open video file {camera.url}")
            return

        registry = self.registry
        frame_idx = 0
        seq = 0
        last_cleanup = time.time()
        offline_shown = False

        while not self.stopped.is_set():
            new_seq, frame = self.source.read(seq)
            if new_seq is None:
                break  # file ended or source released
            if frame is None:
                if not offline_shown and not self.source.online:
                    draw_offline(self.hub, camera)
                    offline_shown = True
                continue
            seq = new_seq
            offline_shown = False
            frame_idx += 1

            # classes=0 -> only 'person'
            results = self.model.track(frame, classes=0, persist=True, verbose=False, conf=DETECT_CONF,
                                       imgsz=camera.imgsz, tracker=TRACKER_CONFIG)
            annotated_frame = frame.copy()
            cv2.line(annotated_frame, (0, camera.line_y), (annotated_frame.shape[1], camera.line_y), (0, 255, 0), 2)
            cv2.putText(annotated_frame, camera.name, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            current_time = time.time()

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().tolist()
                clean, alone = self.crop_quality(boxes, results[0].boxes.conf.cpu().numpy(), frame.shape)

                # Embeddings of clean crops only: always for tracks we haven't seen (needed for stitching),
                # plus a periodic refresh.
                refresh = frame_idx % REID_EVERY_N_FRAMES == 0
                idx = [
                    i for i, t in enumerate(track_ids)
                    if clean[i] and (refresh or t not in registry.by_track)
                ]
                feats = [None] * len(track_ids)
                for i, feat in zip(idx, self.embed_boxes(frame, boxes[idx])):
                    if feat is not None:
                        feats[i] = feat / max(np.linalg.norm(feat), 1e-12)

                people = registry.resolve(track_ids, feats, current_time)
                self.identify_faces(frame, boxes, people, alone, frame_idx)

                for box, person in zip(boxes, people):
                    y = self.anchor_y(box)

                    # Work zone (inside the line = working)
                    if self.is_inside(y):
                        if person.work_since is None:
                            person.work_since = current_time
                    elif person.work_since is not None:
                        person.work_total += current_time - person.work_since
                        person.work_since = None

                    # Line crossing with hysteresis + per-person cooldown
                    side = self.side_of_line(y)
                    if side is not None:
                        if person.side is not None and side != person.side \
                                and current_time - person.last_event >= EVENT_COOLDOWN:
                            action = "ENTER" if side == "inside" else "EXIT"
                            # Re-entering after an EXIT of the same (stitched) person is not a new visit.
                            returning = action == "ENTER" and person.has_event
                            feat = person.reliable_feat
                            # Employees are known by face: the appearance gallery is for anonymous visitors only.
                            is_employee = person.employee_id is not None
                            if action == "ENTER" and not person.has_event and feat is not None and not is_employee:
                                visitor_id, sim = gallery.match(feat, current_time)
                                if visitor_id is not None:
                                    print(f"{self.tag} ReID: person {person.pid} is returning visitor "
                                          f"{visitor_id} (sim={sim:.2f})")
                                    registry.rename(person, visitor_id)
                                    person.returning = returning = True
                            if action == "EXIT" and feat is not None and not is_employee:
                                gallery.add(person.pid, feat, current_time)
                            send_event(camera, person.pid, action, returning, person.employee_id)
                            person.has_event = True
                            person.last_event = current_time
                        person.side = side

                    employee_name = (self.face_gallery.name(person.employee_id)
                                     if person.employee_id is not None and self.face_gallery is not None else None)
                    draw_person(annotated_frame, box, person, current_time, employee_name)
                    # The point that is compared with the line: helps to place line_y when setting up a camera.
                    cv2.circle(annotated_frame, (int((box[0] + box[2]) / 2), y), 5, (0, 255, 255), -1)

            # Forget people who have been gone for a while (keeps memory bounded on long streams).
            if current_time - last_cleanup > 30:
                last_cleanup = current_time
                gallery.prune(current_time)
                registry.prune(current_time)
            if self.face_gallery is not None:
                self.face_gallery.reload()  # picks up new employee photos without a restart

            self.hub.publish(annotated_frame)


app = Flask(__name__)
workers = {}  # camera id -> CameraWorker, in config order


@app.route('/cameras')
def list_cameras():
    return jsonify([
        {
            "id": w.camera.id,
            "name": w.camera.name,
            "branch_id": w.camera.branch_id,
            "online": w.online,
            "running": w.is_alive(),
            "stream": f"/video_feed/{w.camera.id}",
        }
        for w in workers.values()
    ])


@app.route('/video_feed')
def video_feed():
    """Stream of the first camera (kept for the existing frontend)."""
    worker = next(iter(workers.values()))
    return Response(worker.hub.mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_feed/<camera_id>')
def camera_feed(camera_id):
    worker = workers.get(camera_id)
    if worker is None:
        abort(404)
    return Response(worker.hub.mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')


def run_flask():
    app.run(host='0.0.0.0', port=STREAM_PORT, debug=False, use_reloader=False, threaded=True)


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    # docker stop / systemd send SIGTERM: shut down the same way as on Ctrl+C.
    signal.signal(signal.SIGTERM, _raise_interrupt)
    cameras = load_cameras()
    print(f"Starting Computer Vision module with {len(cameras)} camera(s), MJPEG streams on port {STREAM_PORT}...")
    print(f"Detector: {MODEL_PATH}, tracker: {TRACKER_CONFIG}")

    face_gallery = None
    if FACES_ENABLED and any(c.faces for c in cameras):
        face_id.ensure_models()
        face_gallery = face_id.FaceGallery(face_id.FaceModels())
        if len(face_gallery) == 0:
            print(f"Faces: no employee photos in {face_id.FACES_DIR} yet; everyone is counted as a visitor. "
                  f"Add photos as faces/<employee_id>_<name>/*.jpg, they are picked up without a restart.")

    for camera in cameras:
        workers[camera.id] = CameraWorker(camera, face_gallery)
    threading.Thread(target=run_flask, daemon=True).start()
    for worker in workers.values():
        worker.start()

    try:
        # GUI calls must stay on the main thread (macOS requirement), so the preview windows are drawn here.
        shown_seq = {}
        while any(w.is_alive() for w in workers.values()):
            if not SHOW_WINDOW:
                time.sleep(0.5)
                continue
            for w in workers.values():
                with w.hub.cond:
                    frame, seq = w.hub.frame, w.hub.seq
                if frame is not None and shown_seq.get(w.camera.id) != seq:
                    shown_seq[w.camera.id] = seq
                    cv2.imshow(f"CompVision - {w.camera.name}", frame)
            if cv2.waitKey(10) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        pass
    finally:
        for w in workers.values():
            w.stop()
        for w in workers.values():
            w.join(timeout=5)
        if SHOW_WINDOW:
            cv2.destroyAllWindows()
        _event_executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
