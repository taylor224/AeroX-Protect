"""P6 M2 — archive targets + jobs (S3/SMB/local)."""
from types import SimpleNamespace

from tests.conftest import create_user, login


def test_archive_target_crud_no_secret_leak(client):
    h = login(client)
    cr = client.post('/api/v1/archive-targets', headers=h, json={
        'name': 'backup', 'type': 'local', 'config': {'path': '/tmp/axp-arch'},
        'secrets': {'access_key': 'AKIA', 'secret_key': 'SUPERSECRET'}})
    assert cr.status_code == 200, cr.json
    d = cr.json['data']
    assert d['has_secrets'] is True
    assert 'SUPERSECRET' not in str(d) and 'secret_key' not in d   # secrets never serialized
    tid = d['id']

    assert len(client.get('/api/v1/archive-targets', headers=h).json['data']['items']) == 1
    up = client.put(f'/api/v1/archive-targets/{tid}', headers=h, json={'enabled': False})
    assert up.json['data']['enabled'] is False
    assert client.delete(f'/api/v1/archive-targets/{tid}', headers=h).status_code == 200
    assert client.get('/api/v1/archive-targets', headers=h).json['data']['items'] == []


def test_archive_flag_gate(client):
    h = login(client)
    client.put('/api/v1/feature-flags/archiving', headers=h, json={'enabled': False})
    assert client.post('/api/v1/archive-targets', headers=h,
                       json={'name': 'x', 'type': 'local'}).status_code == 403


def test_archive_target_rejects_bad_type(client):
    h = login(client)
    assert client.post('/api/v1/archive-targets', headers=h,
                       json={'name': 'x', 'type': 'ftp'}).status_code == 400


def test_archive_local_driver(tmp_path):
    from server.driver import archive
    src = tmp_path / 'seg.mp4'
    src.write_bytes(b'abc')
    dest = tmp_path / 'arch'
    target = SimpleNamespace(type='local', config={'path': str(dest)}, get_secrets=lambda: {})
    n = archive.upload(target, str(src), 'recording_1/seg_00000.mp4')
    assert n == 3
    assert (dest / 'recording_1' / 'seg_00000.mp4').read_bytes() == b'abc'


def test_archive_job_create_queues(client, monkeypatch):
    from server.task.list import archive as arch_task
    monkeypatch.setattr(arch_task.run_archive_job, 'delay', lambda *a, **k: type('R', (), {'id': 'x'})())
    h = login(client)
    tid = client.post('/api/v1/archive-targets', headers=h,
                      json={'name': 'l', 'type': 'local', 'config': {'path': '/tmp/a'}}).json['data']['id']
    r = client.post('/api/v1/archive-jobs', headers=h, json={'target_id': tid, 'source_ref': '12345'})
    assert r.status_code == 200 and r.json['data']['status'] == 'queued'
    assert len(client.get('/api/v1/archive-jobs', headers=h).json['data']['items']) == 1


def test_archive_run_builds_manifest(client, mock_go2rtc, monkeypatch):
    """archiver.run uploads each segment via the driver and records a manifest."""
    from datetime import datetime

    from server.driver import archive as archive_drv
    from server.model.archive_job import ArchiveJob
    from server.model.archive_target import ArchiveTarget
    from server.model.recording import CLASS_PROTECTED, Recording
    from server.service import archiver

    login(client)
    target = ArchiveTarget.create({'name': 'l', 'type': 'local', 'config': {'path': '/tmp/x'}}, 1)
    rec = Recording.create(camera_id=7, reason='manual', retention_class=CLASS_PROTECTED,
                           start_ts=datetime(2026, 1, 1, 0, 0, 0), end_ts=datetime(2026, 1, 1, 0, 1, 0))

    seg = SimpleNamespace(id=11, disk_id=1, rel_path='a/b.mp4', container='mp4',
                          start_ts=datetime(2026, 1, 1, 0, 0, 0))
    monkeypatch.setattr(archiver.Segment, 'get_range', staticmethod(lambda *a, **k: [seg]))
    monkeypatch.setattr(archiver.Disk, 'get_by_id', staticmethod(lambda _id: SimpleNamespace(id=1)))
    monkeypatch.setattr(archiver.storage_manager, 'abs_path', lambda disk, rel: '/tmp/seg.bin')
    monkeypatch.setattr(archiver.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(archive_drv, 'upload', lambda t, src, name: 1234)

    job = ArchiveJob.create(target.id, 'recording', str(rec.id), 1)
    archiver.run(job.id)
    done = ArchiveJob.get_by_id(job.id)
    assert done.status == 'done' and done.manifest['count'] == 1
    assert done.manifest['items'][0]['bytes'] == 1234
