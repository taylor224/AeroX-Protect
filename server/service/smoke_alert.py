"""Smoke/fire alerting (PLAN P6 A5). A SAFETY-AUXILIARY feature: a dedicated smoke/fire
detector model (not COCO — must be loaded on a node) reports `smoke`/`fire` detections;
this promotes them to `smoke` P3 events (→ outbox→rules/notify). Called from detection
ingest like counting (flag-gated no-op when off). A per-camera Redis cooldown prevents
alert spam. NOTE: this is an *aiding* alert, NOT a certified fire-detection system — the
UI carries that disclaimer; tune threshold + validate before relying on it.
"""
import logging

from server.model.event import TYPE_SMOKE
from server.service import label_map

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 50          # min detection confidence (0–100) to raise an alert
COOLDOWN_SECONDS = 30           # one smoke event per camera per 30s (avoid per-frame spam)


def process_batch(camera_id: int, rows: list[dict]):
    """Raise a `smoke` event for the highest-confidence smoke/fire detection in the batch."""
    from server.service import camera_features
    if not camera_features.is_on(camera_id, 'smoke'):
        return

    candidates = [r for r in rows
                  if r.get('label') in label_map.SMOKE_LABELS and _conf(r) >= _threshold()]
    if not candidates:
        return
    best = max(candidates, key=_conf)
    if not _cooldown_ok(camera_id):
        return

    from server.service import event_pipeline
    try:
        event_pipeline.ingest_object(camera_id, {
            'type': TYPE_SMOKE, 'state': 'pulse', 'subtype': best['label'],
            'source': 'smoke', 'score': _conf(best), 'region': _bbox(best)})
    except Exception:
        logger.exception('smoke event raise failed for camera %s', camera_id)


def _threshold() -> int:
    try:
        from server.model.ai_settings import AiSettings
        s = AiSettings.get_global()
        # reuse min_confidence as the floor, but never below a sane smoke default
        return max(DEFAULT_THRESHOLD, int(s.min_confidence)) if s and s.min_confidence is not None \
            else DEFAULT_THRESHOLD
    except Exception:
        return DEFAULT_THRESHOLD


def _conf(row: dict) -> int:
    try:
        return int(row.get('confidence', 0))
    except (ValueError, TypeError):
        return 0


def _bbox(row: dict):
    b = row.get('bbox')
    return b if isinstance(b, (list, tuple)) and len(b) == 4 else None


def _cooldown_ok(camera_id: int) -> bool:
    """Redis SET NX EX — first caller in the window wins; failures fail-open (alert)."""
    try:
        from server.service.token import get_redis
        r = get_redis()
        return bool(r.set('axp:smoke:cooldown:%s' % camera_id, '1', nx=True, ex=COOLDOWN_SECONDS))
    except Exception:
        return True
