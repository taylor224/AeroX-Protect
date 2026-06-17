"""Face observation ingest (PLAN P7 A8). A detector node (running a face embedder) POSTs
observed face embeddings; this validates against the node's camera assignment (default-deny),
matches each against the known-identity registry, persists `face_observations`, and raises a
`face` event for a KNOWN match (→ outbox→rules/notify). Flag-gated by `face` (off → store
observations but no match/event). FK-free, at-least-once.
"""
import logging
from datetime import datetime

from server.model import utcnow
from server.model.detection_assignment import DetectionAssignment
from server.model.event import TYPE_FACE
from server.model.face_observation import FaceObservation
from server.service import face_match

logger = logging.getLogger(__name__)

MAX_BATCH = 200


def ingest_batch(node, batch: list[dict]) -> dict:
    """Validate + persist a node's face batch. Returns {accepted, rejected, matched}."""
    from server.service import camera_features

    rejected, rows, matched_rows = [], [], []
    assign_cache: dict[int, object] = {}
    feat_cache: dict[int, bool] = {}                     # per-camera face enable
    now = utcnow()

    for idx, rep in enumerate((batch or [])[:MAX_BATCH]):
        reason = _validate(rep, node, assign_cache)
        if reason:
            rejected.append({'idx': idx, 'reason': reason})
            continue
        row = _build_row(rep, node, now)
        cam_id = row['camera_id']
        if cam_id not in feat_cache:
            feat_cache[cam_id] = camera_features.is_on(cam_id, 'face')
        if feat_cache[cam_id]:
            ident, score = face_match.match(row['embedding'], row['backend'])
            if ident is not None:
                row['identity_id'] = ident.id
                row['identity_name'] = ident.name
                row['score'] = score
                matched_rows.append(row)
        rows.append(row)

    ids = FaceObservation.bulk_create(rows) if rows else []
    id_by_row = dict(zip((id(r) for r in rows), ids))

    raised = 0
    for row in matched_rows:
        if _raise_event(row, id_by_row.get(id(row))):
            raised += 1

    return {'accepted': len(ids), 'rejected': rejected, 'matched': raised}


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
    vec = rep.get('embedding')
    if not isinstance(vec, (list, tuple)) or not vec:
        return 'missing_embedding'
    try:
        [float(x) for x in vec]
    except (ValueError, TypeError):
        return 'bad_embedding'                                  # don't let one bad row abort the batch
    if not rep.get('backend'):
        return 'missing_backend'
    return None


def _build_row(rep: dict, node, now: datetime) -> dict:
    vec = [float(x) for x in rep['embedding']]
    return {
        'camera_id': int(rep['camera_id']),
        'ts': _report_ts(rep.get('ts'), now),
        'backend': str(rep['backend'])[:16],
        'dim': len(vec),
        'embedding': vec,
        'quality': _clamp(rep.get('quality')),
        'region': rep.get('region') if isinstance(rep.get('region'), (list, tuple)) else None,
        'node_id': node.id,
    }


def _clamp(v):
    if v is None:
        return None
    try:
        return max(0, min(100, int(v)))
    except (ValueError, TypeError):
        return None


def _report_ts(ts_ms, now: datetime) -> datetime:
    if ts_ms is None:
        return now
    try:
        from server.model import UTC
        return datetime.fromtimestamp(int(ts_ms) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return now


def _raise_event(row: dict, obs_id) -> bool:
    from server.service import event_pipeline
    try:
        ev = event_pipeline.ingest_object(row['camera_id'], {
            'type': TYPE_FACE, 'state': 'pulse', 'subtype': 'known',
            'source': 'face', 'score': row.get('score'), 'region': row.get('region'),
            'dedup_extra': str(row.get('identity_id') or ''),   # distinct identities don't share a cooldown
            'raw': {'identity': row.get('identity_name'), 'identity_id': str(row.get('identity_id') or ''),
                    'obs_id': str(obs_id or '')}})
        return ev is not None
    except Exception:
        logger.exception('face event raise failed for camera %s', row['camera_id'])
        return False
