"""Object-trigger evaluation (PLAN P4 §6.8). A detection row → matching ObjectTrigger →
promote to a P3 event via event_pipeline.ingest_object. Debounce (per-track) + cooldown
(per camera+trigger) live in Redis; P3 then applies its own policy/cooldown (double safety).

Boundary: P4 only *creates* the event; record/notify/discard is decided by P3 policy+schedule."""
import logging
from datetime import timedelta

import config
from server.model import db, utcnow
from server.model.detection import Detection
from server.model.object_trigger import ObjectTrigger
from server.service import event_pipeline

logger = logging.getLogger(__name__)


def evaluate(row: dict, detection_id: int | None = None):
    """Evaluate triggers for one detection row. Returns the created P3 Event or None.
    First matching trigger wins (camera-specific ordered before global)."""
    camera_id = int(row['camera_id'])
    label = row['label']
    confidence = int(row.get('confidence') or 0)
    zone_id = row.get('zone_id')
    track_key = row.get('track_key')
    attrs = row.get('attrs') or {}

    for t in ObjectTrigger.get_candidates(camera_id):
        if label not in (t.labels or []):
            continue
        if confidence < t.min_confidence:
            continue
        if t.zone_id is not None and (zone_id is None or int(zone_id) != int(t.zone_id)):
            continue
        if t.require_zone_entry and not attrs.get('zone_entry'):
            continue
        if t.min_dwell_ms and int(attrs.get('dwell_ms', 0)) < t.min_dwell_ms:
            continue
        if t.min_count > 1 and _concurrent_count(camera_id, label, row.get('ts')) < t.min_count:
            continue
        if t.debounce_per_track and track_key and _seen_track(track_key, t.id):
            continue
        if _within_cooldown(t.id, camera_id):
            continue

        ev = _promote(t, camera_id, label, confidence, row, detection_id)
        if ev is not None:
            _mark_cooldown(t.id, camera_id, t.cooldown_s)
            if t.debounce_per_track and track_key:
                _mark_track(track_key, t.id, t.cooldown_s)
        return ev
    return None


def _promote(trigger, camera_id, label, confidence, row, detection_id):
    normalized = {
        'type': 'object',
        'subtype': trigger.event_subtype or label,
        'source': 'server',
        'score': confidence,
        'region': {'w': 1, 'h': 1, 'shapes': [{'kind': 'box', 'bbox': row.get('bbox')}]},
        'raw': {'trigger_id': str(trigger.id), 'track_key': row.get('track_key'),
                'label': label, 'node_id': str(row.get('node_id')) if row.get('node_id') else None,
                'detection_id': str(detection_id) if detection_id else None,
                'notify': bool(trigger.notify), 'action_hint': trigger.action_hint},
    }
    return event_pipeline.ingest_object(camera_id, normalized)


def _concurrent_count(camera_id: int, label: str, anchor=None) -> int:
    # anchor on the detection's own (camera-clock) ts — Detection.ts may trail
    # server-now by up to the clamp window, which would empty a utcnow()-based window
    since = (anchor or utcnow()) - timedelta(seconds=2)
    rows = db.session.query(Detection.track_id).filter(
        Detection.camera_id == camera_id, Detection.label == label, Detection.ts >= since).distinct().all()
    return len(rows)


# ── Redis debounce/cooldown ─────────────────────────────────────────────────────
def _redis():
    from server.service.token import get_redis
    return get_redis()


def _cd_key(trigger_id, camera_id) -> str:
    return '%s:trig:%s:%s:last' % (config.REDIS_KEY_PREFIX, trigger_id, camera_id)


def _track_key(track_key, trigger_id) -> str:
    return '%s:trig:track:%s:%s' % (config.REDIS_KEY_PREFIX, track_key, trigger_id)


def _within_cooldown(trigger_id, camera_id) -> bool:
    try:
        return _redis().exists(_cd_key(trigger_id, camera_id)) == 1
    except Exception:
        return False


def _mark_cooldown(trigger_id, camera_id, cooldown_s: int):
    try:
        _redis().setex(_cd_key(trigger_id, camera_id), max(1, cooldown_s), '1')
    except Exception:
        pass


def _seen_track(track_key, trigger_id) -> bool:
    try:
        return _redis().exists(_track_key(track_key, trigger_id)) == 1
    except Exception:
        return False


def _mark_track(track_key, trigger_id, cooldown_s: int):
    try:
        _redis().setex(_track_key(track_key, trigger_id), max(60, cooldown_s * 4), '1')
    except Exception:
        pass
