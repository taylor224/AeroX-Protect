"""Recording/live full-audit fixes (2026-06).

Covers the indexer's corrupt-segment guard (zero-byte / unprobeable files produced by
ffmpeg's -segment_atclocktime while the source is down must never enter the playable
index), the final-segment flush on recorder stop (include_newest), and the
midnight-crossing schedule auto-split.
"""
import os
import time

from server.model import db
from server.model.disk import Disk
from server.model.segment import Segment
from tests.conftest import login


def _disk(tmp_path) -> Disk:
    d = Disk()
    d.name = 'rec'
    d.mount_path = str(tmp_path)
    d.role = 'record'
    d.total_bytes = d.free_bytes = 10 ** 12
    db.session.add(d)
    db.session.commit()
    return d


def _write(directory, name, size=256, settled=True):
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / name
    f.write_bytes(b'x' * size)
    if settled:
        old = time.time() - 120
        os.utime(f, (old, old))
    return f


GOOD_PROBE = {'duration_ms': 10000, 'video_codec': 'h264', 'has_audio': False,
              'width': 1920, 'height': 1080}


# ── indexer: corrupt guard ────────────────────────────────────────────────────
def test_zero_byte_segment_indexed_as_corrupt(app_db, monkeypatch, tmp_path):
    """A 0-byte file (source 404'd, atclocktime kept rolling) is recorded corrupt=True,
    excluded from get_range, and NOT counted as recorder progress (return value)."""
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: None)
    disk = _disk(tmp_path)
    cam_id = 9001
    _write(tmp_path / str(cam_id), 'seg-20260101-000000.mp4', size=0)
    _write(tmp_path / str(cam_id), 'seg-20260101-000010.mp4', size=0)

    n = segment_indexer.index_camera_dir(cam_id, disk, 'fmp4')
    assert n == 0                                   # empty segments are not progress
    rows = db.session.query(Segment).filter(Segment.camera_id == cam_id).all()
    assert len(rows) == 1                           # oldest indexed (newest in-progress)
    assert rows[0].corrupt is True
    # playback/HLS/export read path never sees it
    from datetime import datetime
    assert Segment.get_range(cam_id, datetime(2026, 1, 1), datetime(2026, 1, 2)) == []


def test_unprobeable_nonempty_segment_marked_corrupt(app_db, monkeypatch, tmp_path):
    """Non-empty but truncated/unparseable file (probe → duration 0) is corrupt too."""
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: {'duration_ms': 0})
    disk = _disk(tmp_path)
    cam_id = 9002
    _write(tmp_path / str(cam_id), 'seg-20260101-000000.mp4')
    _write(tmp_path / str(cam_id), 'seg-20260101-000010.mp4')

    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4') == 0
    row = db.session.query(Segment).filter(Segment.camera_id == cam_id).one()
    assert row.corrupt is True


def test_valid_segment_still_indexed_normally(app_db, monkeypatch, tmp_path):
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: dict(GOOD_PROBE))
    disk = _disk(tmp_path)
    cam_id = 9003
    _write(tmp_path / str(cam_id), 'seg-20260101-000000.mp4')
    _write(tmp_path / str(cam_id), 'seg-20260101-000010.mp4')

    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4') == 1
    row = db.session.query(Segment).filter(Segment.camera_id == cam_id).one()
    assert row.corrupt is False
    assert row.duration_ms == 10000


# ── indexer: final flush on stop ─────────────────────────────────────────────
def test_include_newest_indexes_final_segment(app_db, monkeypatch, tmp_path):
    """After the recorder process exits, the flushed last file is indexed too
    (regular ticks always skip the newest as in-progress → last segment was lost)."""
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: dict(GOOD_PROBE))
    disk = _disk(tmp_path)
    cam_id = 9004
    _write(tmp_path / str(cam_id), 'seg-20260101-000000.mp4')
    # final segment flushed by SIGINT moments ago — NOT settled yet
    _write(tmp_path / str(cam_id), 'seg-20260101-000010.mp4', settled=False)

    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4') == 1   # normal tick: newest skipped
    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4', include_newest=True) == 1
    rows = db.session.query(Segment).filter(Segment.camera_id == cam_id).all()
    assert len(rows) == 2


def test_include_newest_single_file(app_db, monkeypatch, tmp_path):
    """A stop right after start leaves one file; the ≥2-files rule must not apply."""
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: dict(GOOD_PROBE))
    disk = _disk(tmp_path)
    cam_id = 9005
    _write(tmp_path / str(cam_id), 'seg-20260101-000000.mp4', settled=False)

    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4') == 0
    assert segment_indexer.index_camera_dir(cam_id, disk, 'fmp4', include_newest=True) == 1


# ── schedules: midnight-crossing window ──────────────────────────────────────
CAMERA = {'name': 'Night', 'host': '192.0.2.190', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def test_midnight_crossing_rule_auto_splits(client, mock_go2rtc):
    """Mon 22:00–06:00 'off' becomes Mon 22:00–24:00 + Tue 00:00–06:00."""
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']
    res = client.put(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h,
                     json={'rules': [{'day_of_week': 0, 'start_min': 1320, 'end_min': 360,
                                      'mode': 'off'}]})
    assert res.status_code == 200, res.json
    rules = sorted(res.json['data']['rules'], key=lambda r: (r['day_of_week'], r['start_min']))
    assert len(rules) == 2
    assert (rules[0]['day_of_week'], rules[0]['start_min'], rules[0]['end_min']) == (0, 1320, 1440)
    assert (rules[1]['day_of_week'], rules[1]['start_min'], rules[1]['end_min']) == (1, 0, 360)
    assert all(r['mode'] == 'off' for r in rules)


def test_midnight_split_wraps_sunday_to_monday(client, mock_go2rtc):
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={**CAMERA, 'host': '192.0.2.191'}).json['data']
    res = client.put(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h,
                     json={'rules': [{'day_of_week': 6, 'start_min': 1380, 'end_min': 120,
                                      'mode': 'motion_only'}]})
    assert res.status_code == 200, res.json
    dows = sorted(r['day_of_week'] for r in res.json['data']['rules'])
    assert dows == [0, 6]                            # Sun night + Mon early morning


def test_equal_start_end_rejected(client, mock_go2rtc):
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={**CAMERA, 'host': '192.0.2.192'}).json['data']
    res = client.put(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h,
                     json={'rules': [{'day_of_week': 0, 'start_min': 600, 'end_min': 600,
                                      'mode': 'off'}]})
    assert res.status_code == 400
