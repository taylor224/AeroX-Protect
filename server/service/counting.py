"""Counting + loitering engine (PLAN P6 A2/A3). Fed each detection batch from
detection_ingest. Lines count in/out crossings (track side-flip); regions measure occupancy
and emit loitering when a track dwells ≥ threshold. Per-track state (last side / region entry
time / loiter-emitted) lives in Redis with a TTL so dropped tracks self-expire. flag off →
no-op (no extra cost on the P4 path).
"""
import logging

import config
from server.model.counting import KIND_LINE, KIND_REGION, CountingLine, CountingStat
from server.model.event import TYPE_LOITERING, TYPE_OCCUPANCY
from server.service import feature_flag, geometry
from server.service.token import get_redis

logger = logging.getLogger(__name__)
_TTL = 120
_P = config.REDIS_KEY_PREFIX


def _side_key(line_id, track):
    return '%s:count:side:%s:%s' % (_P, line_id, track)


def _enter_key(line_id, track):
    return '%s:count:enter:%s:%s' % (_P, line_id, track)


def _loiter_key(line_id, track):
    return '%s:count:loiter:%s:%s' % (_P, line_id, track)


def _line_side(px: float, py: float, line: list) -> int:
    (x1, y1), (x2, y2) = line[0], line[1]
    cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    return 1 if cross >= 0 else -1


def _ts_ms(ts) -> int:
    return int(ts.timestamp() * 1000) if hasattr(ts, 'timestamp') else int(ts)


def process_batch(camera_id: int, rows: list[dict]):
    counting_on = feature_flag.is_enabled('object_counting')
    loiter_on = feature_flag.is_enabled('loitering')
    if not (counting_on or loiter_on):
        return
    lines = CountingLine.get_for_camera(camera_id)
    if not lines:
        return
    r = get_redis()
    for line in lines:
        try:
            _process_line(r, camera_id, line, rows, counting_on, loiter_on)
        except Exception:
            logger.exception('counting failed for line %s', line.id)


def _process_line(r, camera_id, line, rows, counting_on, loiter_on):
    members = set()
    bucket_ts = rows[0]['ts'] if rows else None
    for row in rows:
        track = row.get('track_id')
        if track is None:
            continue
        if line.class_filter and row.get('label') not in line.class_filter:
            continue
        bx, by = geometry.bottom_center(row['bbox'])
        ts = row['ts']

        if line.kind == KIND_LINE:
            if counting_on:
                _cross(r, camera_id, line, track, bx, by, ts, row.get('label'))
        else:  # region
            inside = geometry.point_in_polygon(bx, by, line.geometry or [])
            if inside:
                members.add(track)
                if loiter_on:
                    _dwell(r, camera_id, line, track, ts, row.get('label'))
            else:
                r.delete(_enter_key(line.id, track))
                r.delete(_loiter_key(line.id, track))

    if line.kind == KIND_REGION and members and bucket_ts is not None:
        occ = len(members)
        if counting_on:
            CountingStat.record(camera_id, line.id, bucket_ts, occupancy=occ)
        if line.occupancy_threshold and occ > line.occupancy_threshold:
            _emit(camera_id, TYPE_OCCUPANCY, occ, None, line, dedup_extra=str(line.id))


def _cross(r, camera_id, line, track, bx, by, ts, label):
    side = _line_side(bx, by, line.geometry)
    key = _side_key(line.id, track)
    prev = r.get(key)
    r.setex(key, _TTL, str(side))
    if prev is not None and int(prev) != side:
        if side > 0:
            CountingStat.record(camera_id, line.id, ts, in_delta=1, label=label)
        else:
            CountingStat.record(camera_id, line.id, ts, out_delta=1, label=label)


def _dwell(r, camera_id, line, track, ts, label):
    if not line.loiter_threshold_s:
        return
    ekey = _enter_key(line.id, track)
    enter = r.get(ekey)
    now_ms = _ts_ms(ts)
    if enter is None:
        r.setex(ekey, _TTL, str(now_ms))
        return
    dwell_s = (now_ms - int(enter)) / 1000.0
    if dwell_s >= line.loiter_threshold_s and not r.exists(_loiter_key(line.id, track)):
        r.setex(_loiter_key(line.id, track), _TTL, '1')        # emit once per dwell
        # per line+track dedup — two people loitering at once are distinct events,
        # not a cooldown collapse on camera:loitering:<label>
        _emit(camera_id, TYPE_LOITERING, int(dwell_s), label, line,
              dedup_extra='%s:%s' % (line.id, track))


def _emit(camera_id, etype, value, label, line, dedup_extra=None):
    try:
        from server.service import event_pipeline
        payload = {
            'type': etype, 'state': 'pulse', 'subtype': label,
            'score': min(100, int(value)), 'source': 'server',
            'region': {'polygon': line.geometry} if line else None,
        }
        if dedup_extra:
            payload['dedup_extra'] = dedup_extra
        event_pipeline.ingest_object(camera_id, payload)
    except Exception:
        logger.exception('counting emit (%s) failed', etype)
