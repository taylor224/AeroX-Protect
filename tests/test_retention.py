from datetime import timedelta

from server.model import db, utcnow
from server.model.camera import Camera
from server.model.disk import ROLE_RECORD, Disk
from server.model.recording import CLASS_PROTECTED, REASON_MANUAL, Recording
from server.model.segment import Segment
from server.model.storage_policy import StoragePolicy
from server.service.retention_engine import run_retention

MB = 10 ** 6


def _camera() -> Camera:
    c = Camera()
    c.name = 'cam'
    c.host = 'h'
    c.vendor = 'onvif'
    c.driver = 'onvif'
    c.is_enabled = True
    db.session.add(c)
    db.session.commit()
    return c


def _disk() -> Disk:
    d = Disk()
    d.name = 'd'
    d.mount_path = '/tmp/axp_test_retention/d'
    d.role = ROLE_RECORD
    d.total_bytes = 200 * 1024 ** 3
    d.free_bytes = 100 * 1024 ** 3
    db.session.add(d)
    db.session.commit()
    return d


def _policy(cam, **kw):
    p = StoragePolicy()
    p.camera_id = cam.id
    for k, v in kw.items():
        setattr(p, k, v)
    db.session.add(p)
    db.session.commit()
    return p


def _seg(cam, disk, start, dur=10, size=MB):
    return Segment.create(
        camera_id=cam.id, disk_id=disk.id,
        rel_path='%s/seg-%s.mp4' % (cam.id, start.strftime('%Y%m%d-%H%M%S')),
        start_ts=start, end_ts=start + timedelta(seconds=dur), duration_ms=dur * 1000, size_bytes=size)


def _count(cam):
    return len(Segment.get_range(cam.id, utcnow() - timedelta(days=60), utcnow() + timedelta(days=1)))


def test_days_retention_deletes_old(app_db):
    cam, disk = _camera(), _disk()
    _policy(cam, retention_days=7)
    _seg(cam, disk, utcnow() - timedelta(days=10))
    _seg(cam, disk, utcnow() - timedelta(hours=1))
    run_retention()
    assert _count(cam) == 1


def test_protected_segments_survive(app_db):
    cam, disk = _camera(), _disk()
    _policy(cam, retention_days=1)
    old = utcnow() - timedelta(days=5)
    _seg(cam, disk, old)
    Recording.create(cam.id, REASON_MANUAL, CLASS_PROTECTED, old - timedelta(seconds=5), old + timedelta(seconds=30))
    run_retention()
    assert _count(cam) == 1   # protected interval kept it


def test_capacity_delete_oldest(app_db):
    cam, disk = _camera(), _disk()
    _policy(cam, retention_max_bytes=25 * MB, over_capacity_policy='delete_oldest')
    base = utcnow() - timedelta(hours=5)
    for i in range(5):
        _seg(cam, disk, base + timedelta(minutes=i * 10), size=10 * MB)   # 50MB > 25MB cap
    run_retention()
    assert Segment.total_size_for_camera(cam.id) <= 25 * MB


def test_capacity_hard_cap_evicts_protected_event_clips(app_db):
    """retention_max_bytes is a HARD cap: when a camera is over the cap and EVERY segment is
    event-protected, the oldest protected clips are evicted too — otherwise an event-heavy
    camera grows without bound and ignores its configured size limit. Regression for that bug."""
    from server.model.recording import CLASS_EVENT, REASON_EVENT
    cam, disk = _camera(), _disk()
    _policy(cam, retention_max_bytes=25 * MB, over_capacity_policy='delete_oldest')
    base = utcnow() - timedelta(hours=5)
    for i in range(5):                                   # 50MB total, all protected
        st = base + timedelta(minutes=i * 10)
        _seg(cam, disk, st, size=10 * MB)
        Recording.create(cam.id, REASON_EVENT, CLASS_EVENT, st - timedelta(seconds=2), st + timedelta(seconds=12))
    run_retention()
    assert Segment.total_size_for_camera(cam.id) <= 25 * MB   # cap honored despite protection


def test_capacity_drops_unprotected_before_protected(app_db):
    """Under capacity pressure, unprotected continuous segments are dropped before event clips —
    event clips are only evicted when dropping everything else still isn't enough."""
    from server.model.recording import CLASS_EVENT, REASON_EVENT
    cam, disk = _camera(), _disk()
    _policy(cam, retention_max_bytes=25 * MB, over_capacity_policy='delete_oldest')
    base = utcnow() - timedelta(hours=5)
    for i in range(2):                                   # oldest two: protected event clips (20MB)
        st = base + timedelta(minutes=i * 10)
        _seg(cam, disk, st, size=10 * MB)
        Recording.create(cam.id, REASON_EVENT, CLASS_EVENT, st - timedelta(seconds=2), st + timedelta(seconds=12))
    for i in range(2, 5):                                # newer three: unprotected (30MB)
        _seg(cam, disk, base + timedelta(minutes=i * 10), size=10 * MB)
    run_retention()
    # dropping the 30MB of unprotected gets us to 20MB <= 25MB cap → both event clips survive
    assert Segment.total_size_for_camera(cam.id) <= 25 * MB
    assert _count(cam) == 2


def test_capacity_warn_only_keeps_all(app_db):
    cam, disk = _camera(), _disk()
    _policy(cam, retention_max_bytes=5 * MB, over_capacity_policy='warn_only')
    base = utcnow() - timedelta(hours=2)
    for i in range(3):
        _seg(cam, disk, base + timedelta(minutes=i), size=10 * MB)
    result = run_retention()
    assert _count(cam) == 3
    assert any('capacity_exceeded' in w for w in result['warnings'])
