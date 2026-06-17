"""Detection smart-search (PLAN P4 §5.3, §8.1). Filters → index-friendly query, then
groups results into clips (time-adjacent runs → P2 playback windows) or tracks. raw mode
returns paginated detections. Time window + page caps are enforced."""
from collections import OrderedDict, defaultdict
from datetime import timedelta

from server.model import to_epoch_ms
from server.model.detection import Detection

CLIP_GAP_MS = 30_000          # detections within this gap merge into one clip
CLIP_PRE = timedelta(seconds=5)
CLIP_POST = timedelta(seconds=10)
MAX_GROUP_FETCH = 5000        # cap rows pulled for app-side grouping


def search(*, camera_ids=None, labels=None, start=None, end=None, zone_ids=None,
           min_confidence=None, group='clip', page=1, items_per_page=50) -> dict:
    if group == 'raw':
        total, rows = Detection.search(
            camera_ids=camera_ids, labels=labels, start=start, end=end, zone_ids=zone_ids,
            min_confidence=min_confidence, page=page, items_per_page=items_per_page)
        return {'count': total, 'group': 'raw', 'items': [d.to_dict() for d in rows]}

    _, rows = Detection.search(
        camera_ids=camera_ids, labels=labels, start=start, end=end, zone_ids=zone_ids,
        min_confidence=min_confidence, page=1, items_per_page=MAX_GROUP_FETCH, order='asc')
    groups = _group_tracks(rows) if group == 'track' else _group_clips(rows)
    total = len(groups)
    lo = (page - 1) * items_per_page
    return {'count': total, 'group': group, 'items': groups[lo:lo + items_per_page]}


def _group_clips(rows) -> list[dict]:
    by_cam = defaultdict(list)
    for d in rows:
        by_cam[d.camera_id].append(d)
    clips = []
    for cam_id, ds in by_cam.items():
        ds.sort(key=lambda d: d.ts)
        cur = None
        for d in ds:
            if cur and (d.ts - cur['_last']).total_seconds() * 1000 <= CLIP_GAP_MS:
                cur['_last'] = d.ts
                cur['count'] += 1
                cur['labels'].add(d.label)
                cur['track_ids'].add(d.track_id)
                if d.confidence >= cur['top']:
                    cur['top'] = d.confidence
                    cur['rep'] = d
            else:
                if cur:
                    clips.append(cur)
                cur = {'camera_id': cam_id, '_first': d.ts, '_last': d.ts, 'count': 1,
                       'labels': {d.label}, 'track_ids': {d.track_id}, 'top': d.confidence, 'rep': d}
        if cur:
            clips.append(cur)
    clips.sort(key=lambda c: c['_first'], reverse=True)
    return [_clip_dto(c) for c in clips]


def _clip_dto(c) -> dict:
    rep = c['rep']
    return {
        'group': 'clip',
        'camera_id': str(c['camera_id']),
        'start_ts': to_epoch_ms(c['_first'] - CLIP_PRE),
        'end_ts': to_epoch_ms(c['_last'] + CLIP_POST),
        'labels': sorted(l for l in c['labels'] if l),
        'count': c['count'],
        'track_count': len([t for t in c['track_ids'] if t]),
        'top_confidence': c['top'],
        'rep_detection_id': str(rep.id),
        'segment_id': str(rep.segment_id) if rep.segment_id else None,
        'bbox': rep.bbox,
    }


def _group_tracks(rows) -> list[dict]:
    by_track = OrderedDict()
    for d in rows:
        key = d.track_id or d.id
        g = by_track.get(key)
        if g is None:
            by_track[key] = g = {'track_id': d.track_id, 'camera_id': d.camera_id, '_first': d.ts,
                                 '_last': d.ts, 'count': 0, 'labels': set(), 'top': 0, 'rep': d}
        g['count'] += 1
        g['labels'].add(d.label)
        g['_first'] = min(g['_first'], d.ts)
        g['_last'] = max(g['_last'], d.ts)
        if d.confidence >= g['top']:
            g['top'] = d.confidence
            g['rep'] = d
    out = list(by_track.values())
    out.sort(key=lambda g: g['_first'], reverse=True)
    return [_track_dto(g) for g in out]


def _track_dto(g) -> dict:
    rep = g['rep']
    return {
        'group': 'track',
        'track_id': str(g['track_id']) if g['track_id'] else None,
        'camera_id': str(g['camera_id']),
        'start_ts': to_epoch_ms(g['_first']),
        'end_ts': to_epoch_ms(g['_last']),
        'labels': sorted(l for l in g['labels'] if l),
        'count': g['count'],
        'top_confidence': g['top'],
        'rep_detection_id': str(rep.id),
        'segment_id': str(rep.segment_id) if rep.segment_id else None,
        'bbox': rep.bbox,
    }


def overlay_tracks(camera_id: int, start, end, labels=None) -> dict:
    """Playback overlay payload (§5.6): per-track time-series bboxes for [start,end]."""
    rows = Detection.in_window(camera_id, start, end, labels)
    tracks = OrderedDict()
    for d in rows:
        key = d.track_id or d.id
        t = tracks.get(key)
        if t is None:
            tracks[key] = t = {'track_id': str(d.track_id) if d.track_id else str(d.id),
                               'label': d.label, 'points': []}
        t['points'].append({'ts': to_epoch_ms(d.ts), 'bbox': d.bbox, 'conf': d.confidence})
    return {'w': 1, 'h': 1, 'tracks': list(tracks.values())}


def timeline_markers(camera_id: int, start, end, labels=None) -> list[dict]:
    rows = Detection.in_window(camera_id, start, end, labels)
    return [{'ts': to_epoch_ms(d.ts), 'label': d.label, 'count': 1, 'top_conf': d.confidence,
             'track_id': str(d.track_id) if d.track_id else None, 'detection_id': str(d.id)}
            for d in rows]
