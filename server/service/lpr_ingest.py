"""License-plate read ingest (PLAN P7 A7). A detector node (running a plate-OCR model)
POSTs batches of reads; this validates against the node's camera assignment (default-deny,
same as detection ingest), normalizes the text, matches each read against the watchlist,
persists `plate_reads`, and raises an `lpr` event for `deny` hits (→ outbox→rules/notify).
Flag-gated by `lpr` (off → store reads but no match/event). FK-free, at-least-once.
"""
import logging
from datetime import datetime

from server.model import utcnow
from server.model.event import TYPE_LPR
from server.model.detection_assignment import DetectionAssignment
from server.model.plate_list import KIND_DENY, PlateListEntry
from server.model.plate_read import PlateRead
from server.service import plate_normalize

logger = logging.getLogger(__name__)

MAX_BATCH = 200
MIN_CONFIDENCE = 50          # ignore low-confidence OCR noise


def ingest_batch(node, batch: list[dict]) -> dict:
    """Validate + persist a node's plate batch. Returns {accepted, rejected, matched}."""
    from server.service import camera_features

    rejected, rows, matches = [], [], []
    assign_cache: dict[int, object] = {}
    feat_cache: dict[int, bool] = {}                     # per-camera lpr enable
    now = utcnow()

    for idx, rep in enumerate((batch or [])[:MAX_BATCH]):
        reason = _validate(rep, node, assign_cache)
        if reason:
            rejected.append({'idx': idx, 'reason': reason})
            continue
        row = _build_row(rep, node, now)
        cam_id = row['camera_id']
        if cam_id not in feat_cache:
            feat_cache[cam_id] = camera_features.is_on(cam_id, 'lpr')
        entry = PlateListEntry.match(plate_normalize.match_key(row['plate_text'])) if feat_cache[cam_id] else None
        if entry is not None:
            row['list_id'] = entry.id
            row['list_kind'] = entry.kind
        rows.append(row)
        if entry is not None and entry.kind == KIND_DENY:
            matches.append((row, entry))

    ids = PlateRead.bulk_create(rows) if rows else []
    id_by_row = dict(zip((id(r) for r in rows), ids))

    raised = 0
    for row, entry in matches:
        if _raise_event(row, entry, id_by_row.get(id(row))):
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
    if not plate_normalize.normalize(rep.get('plate_text')):
        return 'empty_plate'
    try:
        conf = int(float(rep.get('confidence', 0)))
    except (ValueError, TypeError):
        return 'bad_confidence'                                 # don't let one bad row abort the batch
    if conf < MIN_CONFIDENCE:
        return 'low_confidence'
    return None


def _build_row(rep: dict, node, now: datetime) -> dict:
    raw = str(rep['plate_text']).strip()[:24]
    return {
        'camera_id': int(rep['camera_id']),
        'ts': _report_ts(rep.get('ts'), now),
        'plate_text': raw,
        'plate_key': plate_normalize.normalize(raw),
        'confidence': max(0, min(100, int(float(rep.get('confidence', 0))))),
        'region': rep.get('region') if isinstance(rep.get('region'), (list, tuple)) else None,
        'vehicle_label': (rep.get('vehicle_label') or None),
        'track_id': rep.get('track_id'),
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


def _raise_event(row: dict, entry: PlateListEntry, read_id) -> bool:
    from server.service import event_pipeline
    try:
        ev = event_pipeline.ingest_object(row['camera_id'], {
            'type': TYPE_LPR, 'state': 'pulse', 'subtype': entry.kind,
            'source': 'lpr', 'score': row['confidence'], 'region': row.get('region'),
            'dedup_extra': row['plate_key'],   # distinct plates don't share a cooldown
            'raw': {'plate': row['plate_text'], 'list_label': entry.label, 'read_id': str(read_id or '')}})
        return ev is not None
    except Exception:
        logger.exception('lpr event raise failed for camera %s', row['camera_id'])
        return False
