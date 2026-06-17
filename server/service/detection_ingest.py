"""Node detection-report ingestion (PLAN P4 §5.3, §6.5–6.7). Validates a batch against
the node's assignments (epoch), normalizes labels/coords, derives track_key/track_id,
attributes a zone (bottom-center point-in-polygon), links a P2 segment, bulk-inserts, and
hands accepted detections to the object-trigger engine. FK-free, at-least-once."""
import hashlib
import logging
from datetime import datetime

from server.model import UTC, utcnow
from server.model.detection import Detection
from server.model.detection_assignment import DetectionAssignment
from server.model.detection_zone import KIND_INCLUDE, DetectionZone
from server.model.segment import Segment
from server.service import geometry, label_map

logger = logging.getLogger(__name__)

CLAMP_SECONDS = 60        # |ts - server_now| beyond this → clamp to server_now (§6.6)
MAX_BATCH = 2000


def ingest_batch(node, batch: list[dict], epoch_map: dict | None = None) -> dict:
    """Validate + persist a node's detection batch. Returns {accepted, rejected:[{idx,reason}]}."""
    epoch_map = epoch_map or {}
    rejected = []
    accepted_rows: list[dict] = []
    accepted_reports: list[dict] = []

    assign_cache: dict[int, DetectionAssignment | None] = {}
    zone_cache: dict[int, list] = {}
    now = utcnow()

    for idx, rep in enumerate(batch[:MAX_BATCH]):
        reason = _validate(rep, node, epoch_map, assign_cache)
        if reason:
            rejected.append({'idx': idx, 'reason': reason})
            continue
        row = _build_row(rep, node, now, zone_cache)
        if row is None:
            rejected.append({'idx': idx, 'reason': 'unknown_label'})
            continue
        accepted_rows.append(row)
        accepted_reports.append(rep)

    ids = Detection.bulk_create(accepted_rows) if accepted_rows else []

    # mark per-camera report time (stall detection) + fire triggers
    for cam_id in {r['camera_id'] for r in accepted_rows}:
        DetectionAssignment.mark_report(cam_id)
    if ids:
        _run_triggers(list(zip(ids, accepted_rows)))

    # P6 A2/A3 counting/loitering + A5 smoke/fire (all flag-gated no-ops when off)
    if accepted_rows:
        from server.service import counting, smoke_alert
        rows_by_cam: dict[int, list] = {}
        for row in accepted_rows:
            rows_by_cam.setdefault(row['camera_id'], []).append(row)
        for cam_id, cam_rows in rows_by_cam.items():
            try:
                counting.process_batch(cam_id, cam_rows)
            except Exception:
                logger.exception('counting batch failed for camera %s', cam_id)
            try:
                smoke_alert.process_batch(cam_id, cam_rows)
            except Exception:
                logger.exception('smoke alert batch failed for camera %s', cam_id)

    return {'accepted': len(ids), 'rejected': rejected}


def _validate(rep: dict, node, epoch_map: dict, assign_cache: dict) -> str | None:
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
        return 'not_assigned'                                  # §7.5: only assigned cameras
    rep_epoch = rep.get('epoch')
    if rep_epoch is None:
        rep_epoch = epoch_map.get(str(cam_id), epoch_map.get(cam_id))
    if rep_epoch is not None and int(rep_epoch) != int(a.epoch):
        return 'stale_epoch'                                   # reassigned/returned node
    if not isinstance(rep.get('bbox'), (list, tuple)) or len(rep['bbox']) != 4:
        return 'bad_bbox'
    return None


def _build_row(rep: dict, node, now: datetime, zone_cache: dict) -> dict | None:
    norm = label_map.normalize(rep.get('class_id'), rep.get('label'))
    if norm is None:
        return None
    class_id, label = norm
    cam_id = int(rep['camera_id'])

    bbox = [round(_clamp01(v), 5) for v in rep['bbox']]
    ts = _report_ts(rep.get('ts'), now)
    conf = _conf_int(rep.get('confidence', 0))
    track_key, track_id = _track_ids(rep, node.id, cam_id)
    zone_id = _attribute_zone(cam_id, bbox, zone_cache)
    seg = Segment.get_at(cam_id, ts)

    return {
        'camera_id': cam_id, 'ts': ts, 'class_id': class_id, 'label': label,
        'confidence': conf, 'track_id': track_id, 'track_key': track_key, 'bbox': bbox,
        'frame_w': rep.get('frame_w'), 'frame_h': rep.get('frame_h'),
        'zone_id': zone_id, 'segment_id': seg.id if seg else None,
        'attrs': rep.get('attrs'), 'node_id': node.id,
    }


def _attribute_zone(camera_id: int, bbox: list, zone_cache: dict) -> int | None:
    if camera_id not in zone_cache:
        zone_cache[camera_id] = [z for z in DetectionZone.get_for_camera(camera_id) if z.kind == KIND_INCLUDE]
    includes = zone_cache[camera_id]
    if not includes:
        return None
    bx, by = geometry.bottom_center(bbox)
    hits = [z for z in includes if geometry.point_in_polygon(bx, by, z.polygon)]
    if not hits:
        return None
    hits.sort(key=lambda z: (-z.priority, geometry.polygon_area(z.polygon)))   # priority↑, area↓
    return hits[0].id


def _run_triggers(id_rows: list[tuple[int, dict]]):
    from server.service import object_trigger_engine
    for det_id, row in id_rows:
        try:
            ev = object_trigger_engine.evaluate(row, detection_id=det_id)
            if ev is not None:
                Detection.link_event([det_id], ev.id)
        except Exception:
            logger.exception('trigger eval failed for detection %s', det_id)
            from server.model import db
            db.session.rollback()


# ── small helpers ──────────────────────────────────────────────────────────────
def _clamp01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _conf_int(conf) -> int:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return 0
    c = c * 100 if c <= 1.0 else c
    return max(0, min(100, int(round(c))))


def _report_ts(ts_ms, now: datetime) -> datetime:
    if not ts_ms:
        return now
    try:
        ts = datetime.fromtimestamp(int(ts_ms) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return now
    if abs((ts - now).total_seconds()) > CLAMP_SECONDS:
        return now
    return ts


def _track_ids(rep: dict, node_id: int, camera_id: int) -> tuple[str, int]:
    tk = rep.get('track_key')
    if not tk:
        base = '%s:%s:%s' % (node_id, camera_id, rep.get('bytetrack_id'))
        tk = hashlib.md5(base.encode()).hexdigest()
    tk = str(tk)[:32]
    try:
        tid = int(tk[:15], 16)
    except ValueError:
        tid = int(hashlib.md5(tk.encode()).hexdigest()[:15], 16)
    return tk, tid
