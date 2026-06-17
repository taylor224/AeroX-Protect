"""P6 R6 — edge-recording import (gap-fill from camera SD).

The driver layer (server.driver.edge) talks to real cameras, so it's mocked here. The
unit-tested core is the gap math + import bookkeeping in service/edge_recording.py: find
uncovered intervals, import only the clips that overlap a gap, index them as reason='edge'.
"""
from datetime import datetime, timedelta

from server.model import db
from server.model.disk import Disk
from server.model.segment import REASON_EDGE, Segment
from tests.conftest import login

GB = 1024 ** 3
T0 = datetime(2026, 1, 1, 0, 0, 0)

CAMERA = {'name': 'Edge', 'host': '192.0.2.190', 'vendor': 'hikvision', 'driver': 'isapi',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def _disk(tmp_path) -> Disk:
    d = Disk()
    d.name, d.mount_path, d.role = 'rec', str(tmp_path), 'record'
    d.total_bytes, d.free_bytes, d.reserved_free_bytes, d.weight = 200 * GB, 100 * GB, 0, 100
    d.status, d.enabled = 'online', True
    db.session.add(d)
    db.session.commit()
    return d


def _seg(camera_id, disk_id, start, end, name):
    Segment.create(camera_id=camera_id, disk_id=disk_id, rel_path='%s/%s' % (camera_id, name),
                   start_ts=start, end_ts=end, duration_ms=int((end - start).total_seconds() * 1000),
                   size_bytes=1000, container='fmp4', first_keyframe_ms=0,
                   reason='continuous', storage_tier='cache', stream_role='main')


# ── API: camera edge_recording config ────────────────────────────────────────
def test_camera_edge_recording_config(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    assert cam['edge_recording'] is False
    up = client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={'edge_recording': True})
    assert up.status_code == 200, up.json
    assert client.get(f"/api/v1/cameras/{cam['uuid']}", headers=h).json['data']['edge_recording'] is True


# ── service: gap computation ─────────────────────────────────────────────────
def test_compute_gaps_finds_uncovered(app_db, tmp_path):
    from server.service import edge_recording
    disk = _disk(tmp_path)
    cam_id = 555
    _seg(cam_id, disk.id, T0, T0 + timedelta(seconds=30), 'a.mp4')                       # [0,30]
    _seg(cam_id, disk.id, T0 + timedelta(seconds=90), T0 + timedelta(seconds=120), 'b.mp4')  # [90,120]
    gaps = edge_recording.compute_gaps(cam_id, T0, T0 + timedelta(seconds=120))
    # uncovered = [30,90] only (range ends exactly at 120 = covered)
    assert len(gaps) == 1
    assert gaps[0][0] == T0 + timedelta(seconds=30)
    assert gaps[0][1] == T0 + timedelta(seconds=90)


def test_compute_gaps_full_coverage_none(app_db, tmp_path):
    from server.service import edge_recording
    disk = _disk(tmp_path)
    cam_id = 556
    _seg(cam_id, disk.id, T0, T0 + timedelta(seconds=120), 'full.mp4')
    assert edge_recording.compute_gaps(cam_id, T0, T0 + timedelta(seconds=120)) == []


# ── service: import (mocked driver) ──────────────────────────────────────────
def _camera_row(driver='isapi', edge=True) -> int:
    from server.model.camera import Camera
    c = Camera()
    c.name, c.host, c.driver, c.channel, c.edge_recording = 'EdgeCam', '192.0.2.191', driver, 1, edge
    db.session.add(c)
    db.session.commit()
    return c.id


def test_run_import_fills_only_gaps(app_db, monkeypatch, tmp_path):
    from server.driver import edge as edge_drv
    from server.model.edge_import_job import STATUS_DONE, EdgeImportJob
    from server.model.recording import Recording
    from server.service import edge_recording

    disk = _disk(tmp_path)
    cam_id = _camera_row()
    _seg(cam_id, disk.id, T0, T0 + timedelta(seconds=30), 'have.mp4')   # already have [0,30]

    clips = [
        edge_drv.EdgeClip(T0, T0 + timedelta(seconds=30), 'uri-A'),                       # covered → skip
        edge_drv.EdgeClip(T0 + timedelta(seconds=30), T0 + timedelta(seconds=60), 'uri-B'),  # gap → import
        edge_drv.EdgeClip(T0 + timedelta(seconds=60), T0 + timedelta(seconds=120), 'uri-C'),  # gap → import
    ]
    monkeypatch.setattr(edge_drv, 'search_clips', lambda cam, s, e: list(clips))

    def _dl(cam, clip, dest_abs):
        with open(dest_abs, 'wb') as fh:
            fh.write(b'x' * 2048)
        return 2048
    monkeypatch.setattr(edge_drv, 'download_clip', _dl)

    job = EdgeImportJob.create(cam_id, T0, T0 + timedelta(seconds=120))
    edge_recording.run_import(job.id)

    job = EdgeImportJob.get_by_id(job.id)
    assert job.status == STATUS_DONE
    assert job.clips_found == 3
    assert job.clips_imported == 2                     # clip A (covered) skipped
    assert job.bytes_done == 4096

    edge_segs = db.session.query(Segment).filter(
        Segment.camera_id == cam_id, Segment.reason == REASON_EDGE).all()
    assert len(edge_segs) == 2
    assert all(s.rel_path.startswith('%s/edge/' % cam_id) for s in edge_segs)
    # an 'edge' recording spans the imported window
    rec = db.session.query(Recording).filter(Recording.camera_id == cam_id, Recording.reason == 'edge').first()
    assert rec is not None and rec.start_ts == T0 + timedelta(seconds=30)


def test_run_import_no_gaps_skips_search(app_db, monkeypatch, tmp_path):
    from server.driver import edge as edge_drv
    from server.model.edge_import_job import STATUS_DONE, EdgeImportJob
    from server.service import edge_recording

    disk = _disk(tmp_path)
    cam_id = _camera_row()
    _seg(cam_id, disk.id, T0, T0 + timedelta(seconds=120), 'full.mp4')

    def _boom(*a, **k):
        raise AssertionError('search must not run when there are no gaps')
    monkeypatch.setattr(edge_drv, 'search_clips', _boom)

    job = EdgeImportJob.create(cam_id, T0, T0 + timedelta(seconds=120))
    edge_recording.run_import(job.id)
    job = EdgeImportJob.get_by_id(job.id)
    assert job.status == STATUS_DONE and job.clips_imported == 0


# ── API: preview + import guards ─────────────────────────────────────────────
def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_preview_gaps_endpoint(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.get(f"/api/v1/cameras/{cam['uuid']}/edge/gaps",
                   headers=h, query_string={'start': _ms(T0), 'end': _ms(T0 + timedelta(seconds=120))})
    assert r.status_code == 200, r.json
    # no segments → the whole window is one gap
    gaps = r.json['data']['gaps']
    assert len(gaps) == 1 and gaps[0]['duration_ms'] == 120_000


def test_create_import_requires_camera_flag(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)                       # edge_recording defaults False
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/edge/import",
                    headers=h, json={'range_start': _ms(T0), 'range_end': _ms(T0 + timedelta(seconds=120))})
    assert r.status_code == 400
    assert 'edge_recording' in (r.json.get('message') or '') or 'not enabled' in (r.json.get('message') or '')


def test_create_import_queues(client, mock_go2rtc, monkeypatch):
    from server.task.list import edge_import as task
    monkeypatch.setattr(task.run_edge_import, 'delay', lambda *a, **k: type('R', (), {'id': 'tid'})())
    h = login(client)
    cam = _camera(client, h)
    client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={'edge_recording': True})
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/edge/import",
                    headers=h, json={'range_start': _ms(T0), 'range_end': _ms(T0 + timedelta(seconds=120))})
    assert r.status_code == 200, r.json
    assert r.json['data']['status'] == 'queued'
    jobs = client.get(f"/api/v1/cameras/{cam['uuid']}/edge/jobs", headers=h).json['data']['items']
    assert len(jobs) == 1


# ── auto-import scan ─────────────────────────────────────────────────────────
def test_auto_import_due_queues_and_dedups(app_db, monkeypatch):
    from server.model.camera import Camera
    from server.model.edge_import_job import STATUS_QUEUED, EdgeImportJob
    from server.service import edge_recording
    from server.task.list import edge_import as edge_task

    calls: list = []
    monkeypatch.setattr(edge_task.run_edge_import, 'delay', lambda job_id: calls.append(job_id))

    def _cam(name, edge, auto):
        c = Camera()
        c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'hikvision', 'isapi', True
        c.edge_recording, c.edge_auto_import = edge, auto
        db.session.add(c)
        db.session.commit()
        return c

    eligible = _cam('auto', True, True)       # no segments → whole window is one gap → queue
    _cam('manual_only', True, False)          # edge on, auto off → skip
    _cam('off', False, True)                  # auto on but edge off → skip

    assert edge_recording.auto_import_due() == 1 and len(calls) == 1
    jobs = db.session.query(EdgeImportJob).filter(EdgeImportJob.camera_id == eligible.id).all()
    assert len(jobs) == 1 and jobs[0].status == STATUS_QUEUED

    # a job is already active for that camera → next scan must not queue a duplicate
    assert edge_recording.auto_import_due() == 0 and len(calls) == 1
