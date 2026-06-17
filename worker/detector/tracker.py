"""Greedy IoU tracker (PLAN P4 §6.2, runway_monitor tracker.py generalized). Dependency-free
default; in-container supervision.ByteTrack can replace it. Emits TrackedObjects with a
globally-stable `track_key = md5(session:camera:local_id)[:32]` so server-side grouping
survives worker restarts."""
import hashlib
import itertools


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class TrackedObject:
    def __init__(self, local_id, det, ts_ms, track_key):
        self.local_id = local_id
        self.track_key = track_key
        self.bbox = det.bbox_xyxy
        self.label = det.label
        self.class_id = det.class_id
        self.confidence = det.confidence
        self.first_ts = ts_ms
        self.last_ts = ts_ms
        self.is_new = True
        self.is_lost = False
        self.force = False

    @property
    def dwell_ms(self) -> int:
        return self.last_ts - self.first_ts

    def update(self, det, ts_ms):
        self.bbox = det.bbox_xyxy
        self.label = det.label
        self.class_id = det.class_id
        self.confidence = det.confidence
        self.last_ts = ts_ms
        self.is_new = False


class SimpleTracker:
    def __init__(self, session: str, camera_id: int, iou_thresh: float = 0.3, max_age_ms: int = 2000):
        self.session = session
        self.camera_id = camera_id
        self.iou_thresh = iou_thresh
        self.max_age_ms = max_age_ms
        self._tracks: dict[int, TrackedObject] = {}
        self._ids = itertools.count(1)

    def _key(self, local_id: int) -> str:
        return hashlib.md5(('%s:%s:%s' % (self.session, self.camera_id, local_id)).encode()).hexdigest()[:32]

    def update(self, detections: list, ts_ms: int) -> list[TrackedObject]:
        """Match detections to live tracks (greedy IoU). Returns active + just-lost tracks."""
        live = list(self._tracks.values())
        for t in live:
            t.is_new = False
        unmatched = set(range(len(detections)))
        # greedy: best IoU pairs first
        pairs = []
        for ti, t in enumerate(live):
            for di in unmatched:
                iou = _iou(t.bbox, detections[di].bbox_xyxy)
                if iou >= self.iou_thresh:
                    pairs.append((iou, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for _iou_v, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            live[ti].update(detections[di], ts_ms)
            used_t.add(ti)
            used_d.add(di)
            unmatched.discard(di)

        for di in unmatched:
            local_id = next(self._ids)
            obj = TrackedObject(local_id, detections[di], ts_ms, self._key(local_id))
            self._tracks[local_id] = obj

        # age out stale tracks → emit as lost once
        lost = []
        for local_id, t in list(self._tracks.items()):
            if ts_ms - t.last_ts > self.max_age_ms:
                t.is_lost = True
                lost.append(t)
                del self._tracks[local_id]

        return list(self._tracks.values()) + lost
