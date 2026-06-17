"""Dependency-free detector (PLAN P4 §12). Used by tests and as a graceful fallback when
ultralytics/torch aren't installed — the node still joins/heartbeats/polls (proving the
distributed infra) without real inference. Optionally emits scripted detections."""
from worker.detector.backends.base import Detection


class FakeDetector:
    name = 'fake'

    def __init__(self, spec: dict | None = None):
        self._spec = spec or {}
        self._script = self._spec.get('script')          # optional list[Detection] per call
        self._frame_wh = self._spec.get('frame_wh', (1280, 720))

    def warmup(self):
        pass

    def infer(self, frame, *, imgsz: int = 640, conf: float = 0.35, classes=None) -> list[Detection]:
        if self._script is not None:
            return list(self._script)
        if frame is None:
            return []
        w, h = self._frame_wh
        # deterministic single 'person' box in the central third (≥ conf)
        det = Detection(bbox_xyxy=(w * 0.4, h * 0.3, w * 0.6, h * 0.9), confidence=0.9, class_id=0, label='person')
        if classes is not None and 0 not in classes:
            return []
        return [det] if det.confidence >= conf else []

    def benchmark(self, sample) -> dict:
        return {'fps_per_cam': 999, 'vram_mb': 0, 'capacity': 99}

    @property
    def healthy(self) -> bool:
        return True

    @property
    def device(self) -> str:
        return 'fake'

    def close(self):
        pass
