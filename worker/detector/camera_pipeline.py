"""Per-camera pipeline (PLAN P4 §6.2): capture → infer → zone filter → track → sample →
report. One thread per assigned camera; reports (normalized 0–1 bbox) go to the agent's
queue for batched POST /ai/ingest/detections. cv2 is lazy (in source.py)."""
import logging
import threading
import time

from worker.detector.sampler import TrackSampler
from worker.detector.source import Go2rtcSource
from worker.detector.tracker import SimpleTracker
from worker.detector.zones import ZoneFilter

logger = logging.getLogger(__name__)


class CameraPipeline:
    def __init__(self, spec: dict, backend, report_q, session: str):
        self.backend = backend
        self.report_q = report_q
        self.session = session
        self._running = False
        self._thread = None
        self._last_frame = -1
        self.apply(spec)

    def apply(self, spec: dict):
        self.spec = spec
        self.camera_id = spec['camera_id']
        self.epoch = spec.get('epoch', 0)
        self.imgsz = spec.get('imgsz', 640)
        self.conf = (spec.get('min_confidence', 35) or 35) / 100.0
        self.target_fps = max(1, spec.get('target_fps', 5))
        self.labels = set(spec.get('labels') or [])
        self.zones = ZoneFilter(spec.get('zones'))
        self.sample_interval = spec.get('sample_interval_ms', 1000)
        if not getattr(self, '_thread', None):
            self.tracker = SimpleTracker(self.session, self.camera_id)
            self.sampler = TrackSampler(self.sample_interval)
            self.source = Go2rtcSource(spec['rtsp_url'], self.target_fps)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name='cam-%s' % self.camera_id, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.source.close()

    def _loop(self):
        interval = 1.0 / self.target_fps
        while self._running:
            t0 = time.monotonic()
            try:
                frame, frame_id, ms = self.source.read()
                if frame is None or frame_id == self._last_frame:
                    time.sleep(0.05)
                    continue
                self._last_frame = frame_id
                dets = self.backend.infer(frame, imgsz=self.imgsz, conf=self.conf, classes=None)
                if self.labels:
                    dets = [d for d in dets if d.label in self.labels]
                w, h = Go2rtcSource.frame_size(frame)
                dets = self.zones.filter(dets, w, h)
                tracks = self.tracker.update(dets, ms)
                reports = [self._report(t, ms, w, h) for t in self.sampler.sample(tracks, ms)]
                if reports:
                    self.report_q.put(reports)
            except Exception:
                logger.exception('pipeline %s loop error', getattr(self, 'camera_id', '?'))
                time.sleep(0.3)
            dt = time.monotonic() - t0
            if dt < interval:
                time.sleep(interval - dt)

    def _report(self, t, ms: int, w: int, h: int) -> dict:
        x1, y1, x2, y2 = t.bbox
        return {
            'camera_id': self.camera_id, 'ts': ms, 'epoch': self.epoch,
            'label': t.label, 'class_id': t.class_id, 'confidence': t.confidence,
            'bbox': [x1 / w, y1 / h, x2 / w, y2 / h], 'frame_w': w, 'frame_h': h,
            'track_key': t.track_key, 'bytetrack_id': t.local_id,
            'attrs': {'dwell_ms': t.dwell_ms},
        }
