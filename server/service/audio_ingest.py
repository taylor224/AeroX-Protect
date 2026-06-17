"""Audio-classification ingest (PLAN P6 A4). A detector node POSTs batches of classified
audio windows; this validates them against the node's camera assignment (same default-deny
as detection ingest), persists `audio_detections`, and promotes any window scoring at/above
the global `ai_settings.audio_threshold` to an `audio_class` P3 event (→ outbox→rules/notify).
Flag-gated by `audio_detection` (off = accept+store but never raise events). FK-free,
at-least-once.
"""
import logging
from datetime import datetime

from server.model import utcnow
from server.model.ai_settings import AiSettings
from server.model.audio_detection import AudioDetection
from server.model.detection_assignment import DetectionAssignment
from server.model.event import TYPE_AUDIO_CLASS

logger = logging.getLogger(__name__)

MAX_BATCH = 200
DEFAULT_THRESHOLD = 60


def ingest_batch(node, batch: list[dict]) -> dict:
    """Validate + persist a node's audio batch. Returns {accepted, rejected:[{idx,reason}]}."""
    rejected = []
    accepted_rows: list[dict] = []
    assign_cache: dict[int, object] = {}
    now = utcnow()

    for idx, rep in enumerate((batch or [])[:MAX_BATCH]):
        reason = _validate(rep, node, assign_cache)
        if reason:
            rejected.append({'idx': idx, 'reason': reason})
            continue
        accepted_rows.append(_build_row(rep, node, now))

    ids = AudioDetection.bulk_create(accepted_rows) if accepted_rows else []

    # promote high-confidence windows to events (per-camera ai_features.audio)
    from server.service import camera_features
    if ids:
        threshold = _threshold()
        for row in accepted_rows:
            if row['score'] >= threshold and camera_features.is_on(row['camera_id'], 'audio'):
                _raise_event(row)

    return {'accepted': len(ids), 'rejected': rejected}


def _threshold() -> int:
    try:
        s = AiSettings.get_global()
        return int(s.audio_threshold) if s and s.audio_threshold is not None else DEFAULT_THRESHOLD
    except Exception:
        return DEFAULT_THRESHOLD


def _validate(rep: dict, node, assign_cache: dict) -> str | None:
    cam_id = rep.get('camera_id')
    if not cam_id:
        return 'missing_camera'
    try:
        cam_id = int(cam_id)
    except (ValueError, TypeError):
        return 'bad_camera_id'                                  # don't let one bad row abort the batch
    if cam_id not in assign_cache:
        assign_cache[cam_id] = DetectionAssignment.get_for_camera(cam_id)
    a = assign_cache[cam_id]
    if a is None or int(a.node_id) != int(node.id):
        return 'not_assigned'
    if not rep.get('label'):
        return 'missing_label'
    return None


def _build_row(rep: dict, node, now: datetime) -> dict:
    return {
        'camera_id': int(rep['camera_id']),
        'ts': _report_ts(rep.get('ts'), now),
        'label': str(rep['label'])[:32],
        'score': max(0, min(100, int(rep.get('score', 0)))),
        'clip_path': rep.get('clip_path'),
        'node_id': node.id,
    }


def _report_ts(ts_ms, now: datetime) -> datetime:
    if ts_ms is None:
        return now
    try:
        from server.model import UTC
        return datetime.fromtimestamp(int(ts_ms) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return now


def _raise_event(row: dict):
    from server.service import event_pipeline
    try:
        event_pipeline.ingest_object(row['camera_id'], {
            'type': TYPE_AUDIO_CLASS, 'state': 'pulse', 'subtype': row['label'],
            'source': 'audio', 'score': row['score']})
    except Exception:
        logger.exception('audio_class event raise failed for camera %s', row['camera_id'])
