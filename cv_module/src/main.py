import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import requests
from dotenv import load_dotenv
from flask import Flask, Response
from ultralytics import YOLO
from ultralytics.trackers.utils.reid import ReID, smooth_feature

load_dotenv()

# Configuration
API_URL = os.getenv("API_URL", "http://127.0.0.1:8002")
BRANCH_ID = int(os.getenv("BRANCH_ID", "1"))
RTSP_URL = os.getenv("RTSP_URL", "0")  # 0 for webcam
STREAM_PORT = int(os.getenv("STREAM_PORT", "5002"))
MODEL_PATH = os.getenv("MODEL_PATH", "yolo26s.pt")
TRACKER_CONFIG = os.getenv(
    "TRACKER_CONFIG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trackers", "botsort_cctv.yaml")
)
SHOW_WINDOW = os.getenv("SHOW_WINDOW", "1") == "1"

# Line crossing settings
LINE_Y = int(os.getenv("LINE_Y", "300"))
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
REID_THRESHOLDS = os.getenv("REID_THRESHOLDS", "5:0.70,15:0.75,30:0.80")
REID_EVERY_N_FRAMES = int(os.getenv("REID_EVERY_N_FRAMES", "5"))
REID_MIN_BOX_H = int(os.getenv("REID_MIN_BOX_H", "80"))  # smaller crops give unreliable embeddings
REID_EMA = float(os.getenv("REID_EMA", "0.9"))  # weight of the running average vs. the newest embedding
# Track stitching: when the tracker loses someone (occlusion, missed detections) and starts a new track,
# the new track inherits the ID of a person who vanished within REID_STITCH_SEC and looks similar enough.
REID_STITCH_SEC = float(os.getenv("REID_STITCH_SEC", "10"))
REID_STITCH_THRESH = float(os.getenv("REID_STITCH_THRESH", "0.72"))
PERSON_FORGET_SEC = 120.0  # drop state of people not seen this long

model = YOLO(MODEL_PATH)


def _parse_thresholds(spec: str):
    steps = []
    for part in spec.split(","):
        minutes, sim = part.split(":")
        steps.append((float(minutes) * 60, float(sim)))
    return sorted(steps)


class ReturnGallery:
    """Short-lived memory of people who recently exited, used to recognise them on re-entry."""

    def __init__(self, ttl_sec: float, thresholds):
        self.ttl_sec = ttl_sec
        self.thresholds = thresholds
        self.entries = {}  # visitor_id -> (embedding, exit_time)

    def _threshold(self, away_sec: float):
        for max_away, sim in self.thresholds:
            if away_sec <= max_away:
                return sim
        return None  # away longer than the last step -> treat as a new visit

    def prune(self, now: float):
        self.entries = {v: e for v, e in self.entries.items() if now - e[1] <= self.ttl_sec}

    def add(self, visitor_id: int, embedding: np.ndarray, now: float):
        self.entries[visitor_id] = (embedding, now)

    def match(self, embedding: np.ndarray, now: float):
        """Returns (visitor_id, similarity) of the best match above its time-based threshold, else (None, best_sim)."""
        self.prune(now)
        best_id, best_match_sim, best_sim = None, -1.0, -1.0
        for visitor_id, (emb, exit_time) in self.entries.items():
            sim = float(np.dot(embedding, emb))
            best_sim = max(best_sim, sim)
            threshold = self._threshold(now - exit_time)
            if threshold is not None and sim >= threshold and sim > best_match_sim:
                best_id, best_match_sim = visitor_id, sim
        if best_id is not None:
            best_sim = best_match_sim
            del self.entries[best_id]  # one exit can be matched by one entry only
        return best_id, best_sim


reid_encoder = ReID(REID_MODEL)  # also used for track stitching, so it is always loaded
gallery = ReturnGallery(REID_TTL_MIN * 60, _parse_thresholds(REID_THRESHOLDS))

# Events are sent in the background so a slow API never stalls video processing.
_event_executor = ThreadPoolExecutor(max_workers=2)


def _post_event(payload: dict):
    try:
        response = requests.post(f"{API_URL}/events/", json=payload, timeout=API_TIMEOUT)
        response.raise_for_status()
        print(f"Event sent successfully: {payload}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send event to API: {e}")


def send_event(person_id: int, action: str, returning: bool = False):
    """Queues an event ("ENTER" or "EXIT") for the backend API.

    person_id is an anonymous visitor id that survives a short exit/re-entry (see ReID),
    so counting distinct person_id values gives the number of visits.
    """
    payload = {
        "branch_id": BRANCH_ID,
        "person_id": person_id,
        "action": action,
        "timestamp": time.time(),
        "returning": returning,
    }
    _event_executor.submit(_post_event, payload)


app = Flask(__name__)

# Latest encoded JPEG shared with stream clients; the condition wakes them on each new frame.
_frame_cond = threading.Condition()
_frame_jpeg = None
_frame_seq = 0


def publish_frame(frame):
    global _frame_jpeg, _frame_seq
    ok, buffer = cv2.imencode('.jpg', frame)
    if not ok:
        return
    with _frame_cond:
        _frame_jpeg = buffer.tobytes()
        _frame_seq += 1
        _frame_cond.notify_all()


def generate_frames():
    last_seq = 0
    min_interval = 1.0 / STREAM_MAX_FPS if STREAM_MAX_FPS > 0 else 0
    last_sent = 0.0
    while True:
        with _frame_cond:
            # Wait for a frame newer than the one already sent to this client.
            _frame_cond.wait_for(lambda: _frame_seq != last_seq, timeout=1.0)
            if _frame_seq == last_seq or _frame_jpeg is None:
                continue
            last_seq = _frame_seq
            jpeg = _frame_jpeg

        wait = min_interval - (time.time() - last_sent)
        if wait > 0:
            time.sleep(wait)
        last_sent = time.time()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


def run_flask():
    app.run(host='0.0.0.0', port=STREAM_PORT, debug=False, use_reloader=False, threaded=True)


def side_of_line(center_y: int):
    """Returns 'above', 'below' or None while inside the dead zone around the line."""
    if center_y < LINE_Y - LINE_MARGIN:
        return "above"
    if center_y > LINE_Y + LINE_MARGIN:
        return "below"
    return None


def embed_boxes(frame, boxes_xyxy):
    """Returns one L2-normalised appearance embedding (or None) per xyxy box."""
    if reid_encoder is None or len(boxes_xyxy) == 0:
        return [None] * len(boxes_xyxy)
    b = np.asarray(boxes_xyxy, dtype=np.float32)
    xywh = np.stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], axis=1)
    return reid_encoder(frame, xywh)


@dataclass
class Person:
    """A person as we see them, independent of the tracker's (unstable) track ids."""
    pid: int                              # stable anonymous id: shown on video and sent to the API
    last_seen: float
    feat: Optional[np.ndarray] = None     # smoothed appearance embedding (RAM only)
    side: Optional[str] = None            # last confirmed side of the line
    last_event: float = 0.0
    has_event: bool = False
    returning: bool = False
    work_total: float = 0.0
    work_since: Optional[float] = None

    def update_feat(self, feat):
        if feat is not None:
            _, self.feat = smooth_feature(feat, self.feat, REID_EMA)


class PersonRegistry:
    """Maps tracker ids to stable people and stitches broken tracks back together by appearance."""

    def __init__(self):
        self.people = {}       # pid -> Person
        self.by_track = {}     # tracker id -> Person
        self.next_pid = 1
        self.tracker_ids_seen = set()

    def _new_person(self, now):
        person = Person(pid=self.next_pid, last_seen=now)
        self.next_pid += 1
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
            print(f"ReID: track {track_ids[i]} continues person {p.pid} (sim={sim:.2f})")

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


def draw_person(frame, box, person, now):
    x1, y1, x2, y2 = map(int, box)
    working = person.work_since is not None
    color = (0, 200, 0) if working else (0, 0, 230)
    worked = person.work_total + (now - person.work_since if working else 0)
    label = f"ID {person.pid}" + (" RETURN" if person.returning else "")
    status = f"{'WORKING' if working else 'IDLE'} | Work: {int(worked)}s"
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
    cv2.putText(frame, label, (x1 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, status, (x1, y2 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def main():
    cap = cv2.VideoCapture(int(RTSP_URL) if RTSP_URL.isdigit() else RTSP_URL)

    if not cap.isOpened():
        print("Error: Could not open video source.")
        return

    print(f"Starting Computer Vision module and MJPEG Stream on port {STREAM_PORT}...")
    print(f"Detector: {MODEL_PATH}, tracker: {TRACKER_CONFIG}")
    threading.Thread(target=run_flask, daemon=True).start()

    registry = PersonRegistry()
    frame_idx = 0
    last_cleanup = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        # classes=0 -> only 'person'
        results = model.track(frame, classes=0, persist=True, verbose=False, conf=0.25, tracker=TRACKER_CONFIG)
        annotated_frame = frame.copy()
        cv2.line(annotated_frame, (0, LINE_Y), (annotated_frame.shape[1], LINE_Y), (0, 255, 0), 2)
        current_time = time.time()

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().tolist()

            # Embeddings: always for tracks we haven't seen (needed for stitching), plus a periodic refresh.
            refresh = frame_idx % REID_EVERY_N_FRAMES == 0
            idx = [
                i for i, (b, t) in enumerate(zip(boxes, track_ids))
                if b[3] - b[1] >= REID_MIN_BOX_H and (refresh or t not in registry.by_track)
            ]
            feats = [None] * len(track_ids)
            for i, feat in zip(idx, embed_boxes(frame, boxes[idx])):
                if feat is not None:
                    feats[i] = feat / max(np.linalg.norm(feat), 1e-12)

            people = registry.resolve(track_ids, feats, current_time)

            for box, person in zip(boxes, people):
                center_y = int((box[1] + box[3]) // 2)

                # Work zone (below the line = working)
                if center_y > LINE_Y:
                    if person.work_since is None:
                        person.work_since = current_time
                elif person.work_since is not None:
                    person.work_total += current_time - person.work_since
                    person.work_since = None

                # Line crossing with hysteresis + per-person cooldown
                side = side_of_line(center_y)
                if side is not None:
                    if person.side is not None and side != person.side \
                            and current_time - person.last_event >= EVENT_COOLDOWN:
                        action = "ENTER" if side == "below" else "EXIT"
                        # Re-entering after an EXIT of the same (stitched) person is not a new visit.
                        returning = action == "ENTER" and person.has_event
                        if action == "ENTER" and not person.has_event and person.feat is not None:
                            visitor_id, sim = gallery.match(person.feat, current_time)
                            if visitor_id is not None:
                                print(f"ReID: person {person.pid} is returning visitor {visitor_id} (sim={sim:.2f})")
                                registry.rename(person, visitor_id)
                                person.returning = returning = True
                        if action == "EXIT" and person.feat is not None:
                            gallery.add(person.pid, person.feat, current_time)
                        send_event(person.pid, action, returning)
                        person.has_event = True
                        person.last_event = current_time
                    person.side = side

                draw_person(annotated_frame, box, person, current_time)

        # Forget people who have been gone for a while (keeps memory bounded on long streams).
        if current_time - last_cleanup > 30:
            last_cleanup = current_time
            gallery.prune(current_time)
            registry.prune(current_time)

        publish_frame(annotated_frame)

        if SHOW_WINDOW:
            cv2.imshow("CompVision Edge Agent", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    print(f"Stopped: tracker issued {len(registry.tracker_ids_seen)} track ids, "
          f"shown as {registry.next_pid - 1} people after ReID stitching.")
    cap.release()
    if SHOW_WINDOW:
        cv2.destroyAllWindows()
    _event_executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
