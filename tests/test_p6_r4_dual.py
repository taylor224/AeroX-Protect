"""P6 R4 — opt-in dual recording (record the sub stream alongside the main one).

Design intent under test: dual recording is fully isolated from the critical main
recorder. The supervisor runs a SEPARATE sub_procs map, writes sub segments to
{disk}/{cam}/sub/ tagged stream_role='sub', and never writes recorder health. Real
ffmpeg/go2rtc are unavailable here, so we exercise the deterministic logic: the camera
config flag, the indexer's role/path attribution, sub-stream selection, and the tick
convergence (which cameras get a sub recorder), with subprocess.Popen mocked.
"""
import os
import time

from server.model import db
from server.model.disk import Disk
from server.model.segment import Segment
from tests.conftest import login

CAMERA = {'name': 'Dual', 'host': '192.0.2.180', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}, {'role': 'sub', 'rtsp_path': '/sub'}]}


# ── API: camera dual_recording config ────────────────────────────────────────
def test_camera_dual_recording_config(client, mock_go2rtc):
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']
    assert cam['dual_recording'] is False                      # opt-in, default OFF
    up = client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={'dual_recording': True})
    assert up.status_code == 200, up.json
    got = client.get(f"/api/v1/cameras/{cam['uuid']}", headers=h).json['data']
    assert got['dual_recording'] is True
    # toggling back off
    client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={'dual_recording': False})
    assert client.get(f"/api/v1/cameras/{cam['uuid']}", headers=h).json['data']['dual_recording'] is False


# ── indexer: role + path attribution ─────────────────────────────────────────
def _disk(tmp_path) -> Disk:
    d = Disk()
    d.name = 'rec'
    d.mount_path = str(tmp_path)
    d.role = 'record'
    d.total_bytes = d.free_bytes = 10 ** 12
    db.session.add(d)
    db.session.commit()
    return d


def _write_segments(directory, names):
    directory.mkdir(parents=True, exist_ok=True)
    old = time.time() - 120          # well past SETTLE_SECONDS so files count as settled
    for name in names:
        f = directory / name
        f.write_bytes(b'x' * 256)
        os.utime(f, (old, old))


def test_indexer_tags_sub_role_and_path(app_db, monkeypatch, tmp_path):
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: {
        'duration_ms': 10000, 'video_codec': 'h264', 'has_audio': False, 'width': 640, 'height': 360})
    disk = _disk(tmp_path)
    cam_id = 777
    _write_segments(tmp_path / str(cam_id) / 'sub',
                    ['seg-20260101-000000.mp4', 'seg-20260101-000010.mp4', 'seg-20260101-000020.mp4'])

    n = segment_indexer.index_camera_dir(cam_id, disk, 'fmp4', subdir='sub', stream_role='sub')
    assert n == 2                                              # 3 files, newest skipped (in-progress)
    rows = db.session.query(Segment).filter(Segment.camera_id == cam_id).all()
    assert len(rows) == 2
    assert all(r.stream_role == 'sub' for r in rows)
    assert all(r.rel_path.startswith('%s/sub/' % cam_id) for r in rows)


def test_indexer_main_role_default_unaffected(app_db, monkeypatch, tmp_path):
    """The existing main-stream call (no subdir/role args) still tags 'main' under {cam}/."""
    from server.service import ffmpeg, segment_indexer
    monkeypatch.setattr(ffmpeg, 'probe', lambda path, timeout=20: {
        'duration_ms': 10000, 'video_codec': 'h264', 'has_audio': False, 'width': 1920, 'height': 1080})
    disk = _disk(tmp_path)
    cam_id = 888
    _write_segments(tmp_path / str(cam_id),
                    ['seg-20260101-000000.mp4', 'seg-20260101-000010.mp4'])

    n = segment_indexer.index_camera_dir(cam_id, disk, 'fmp4')
    assert n == 1
    row = db.session.query(Segment).filter(Segment.camera_id == cam_id).first()
    assert row.stream_role == 'main'
    assert row.rel_path == '%s/seg-20260101-000000.mp4' % cam_id
    assert '/sub/' not in row.rel_path


# ── supervisor: sub-stream selection + tick isolation ────────────────────────
class _Stream:
    def __init__(self, sid, role, full=False, live=False):
        self.id, self.role, self.is_default_full, self.is_default_live = sid, role, full, live
        self.go2rtc_name = 'cam_%s' % role


class _Cam:
    def __init__(self, cid, streams, dual=True):
        self.id, self.streams, self.dual_recording = cid, streams, dual


def test_sub_stream_selection():
    from worker.recorder.supervisor import RecorderSupervisor
    s = RecorderSupervisor()
    main = _Stream(10, 'main', full=True)

    # explicit sub role wins
    sub = _Stream(11, 'sub')
    assert s._sub_stream(_Cam(1, [main, sub])).id == 11
    # main is always the recorded main stream (distinct from sub)
    assert s._record_stream(_Cam(1, [main, sub])).id == 10
    # no second stream → nothing to dual-record
    assert s._sub_stream(_Cam(2, [main])) is None
    # no explicit 'sub' but a distinct default-live stream → that one
    live = _Stream(12, 'low', live=True)
    assert s._sub_stream(_Cam(3, [main, live])).id == 12
    # fall back to any non-main stream
    other = _Stream(13, 'third')
    assert s._sub_stream(_Cam(4, [main, other])).id == 13


def test_tick_subs_starts_only_dual_cameras(app_db, monkeypatch, tmp_path):
    from worker.recorder import supervisor as sup

    class _Disk:
        id, name, mount_path = 1, 'd', str(tmp_path)

    class _Popen:
        def __init__(self, *a, **k):
            self.pid = 4242

        def poll(self):
            return None                      # pretend still running

        def send_signal(self, sig):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(sup.storage_manager, 'pick_write_disk', lambda cid, pol: _Disk())
    monkeypatch.setattr(sup.StoragePolicy, 'get_for_camera', lambda cid: None)
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)

    s = sup.RecorderSupervisor()
    dual = _Cam(100, [_Stream(10, 'main', full=True), _Stream(11, 'sub')], dual=True)
    plain = _Cam(101, [_Stream(20, 'main', full=True)], dual=False)
    s._tick_subs([dual, plain])
    assert 100 in s.sub_procs            # dual camera got an isolated sub recorder
    assert 101 not in s.sub_procs        # non-dual camera did not
    assert os.path.isdir(tmp_path / '100' / 'sub')   # sub segments land under {cam}/sub/

    # a dual camera with only the main stream → no sub stream → no proc spawned
    single = _Cam(102, [_Stream(30, 'main', full=True)], dual=True)
    s._tick_subs([dual, single])
    assert 102 not in s.sub_procs

    # disabling dual recording stops the sub recorder on the next tick
    dual.dual_recording = False
    s._tick_subs([dual])
    assert 100 not in s.sub_procs
