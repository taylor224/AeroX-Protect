"""Detector backend factory (PLAN P4 §5.4). Priority: force_backend > YOLO (cuda/cpu via
gpu_enabled) > FakeDetector fallback (ultralytics/torch absent → node still runs the
distributed infra without real inference)."""
import logging

logger = logging.getLogger(__name__)


def make_detector(spec: dict):
    force = spec.get('force_backend')
    if force == 'fake':
        from worker.detector.backends.fake import FakeDetector
        return FakeDetector(spec)
    try:
        from worker.detector.backends.yolo import YoloDetector
        det = YoloDetector(spec)
        det.warmup()
        return det
    except Exception as exc:
        logger.warning('YOLO backend unavailable (%s) — using FakeDetector', exc)
        from worker.detector.backends.fake import FakeDetector
        return FakeDetector(spec)
