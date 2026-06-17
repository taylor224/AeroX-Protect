from datetime import timedelta

from server.model import to_epoch_ms, utcnow
from tests.conftest import create_user, login

CAMERA = {'name': 'Rec', 'host': '192.0.2.5', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _create_camera(client, headers):
    return client.post('/api/v1/cameras', headers=headers, json=CAMERA).json['data']


# ── storage ───────────────────────────────────────────────────────────────────
def test_disk_register_and_pool(client, tmp_path):
    h = login(client)
    r = client.post('/api/v1/storage/disks', headers=h,
                    json={'name': 'D1', 'mount_path': str(tmp_path), 'role': 'record', 'reserved_free_bytes': 0})
    assert r.status_code == 200, r.json
    assert r.json['data']['total_bytes'] > 0   # usage scanned
    assert client.get('/api/v1/storage/disks', headers=h).json['data']['disks']
    assert client.get('/api/v1/storage/pool', headers=h).status_code == 200


def test_disk_register_rejects_nonwritable(client):
    h = login(client)
    r = client.post('/api/v1/storage/disks', headers=h,
                    json={'name': 'X', 'mount_path': '/nonexistent/xyz', 'role': 'record'})
    assert r.status_code == 400


def test_policy_update(client, mock_go2rtc):
    h = login(client)
    cam = _create_camera(client, h)
    r = client.put(f"/api/v1/storage/policies/{cam['uuid']}", headers=h,
                   json={'record_mode': 'continuous', 'retention_days': 30})
    assert r.status_code == 200
    assert r.json['data']['record_mode'] == 'continuous'
    assert 'warnings' in r.json['data']


def test_storage_requires_permission(client):
    h = login(client)
    create_user(client, h, 'nostorage', {'cameras': ['read']})
    vh = login(client, 'nostorage', 'viewer1234!')
    assert client.get('/api/v1/storage/disks', headers=vh).status_code == 403


# ── recording ─────────────────────────────────────────────────────────────────
def test_recording_mode_toggle(client, mock_go2rtc):
    h = login(client)
    cam = _create_camera(client, h)
    r = client.put(f"/api/v1/recording/cameras/{cam['uuid']}/mode", headers=h, json={'mode': 'continuous'})
    assert r.status_code == 200 and r.json['data']['record_mode'] == 'continuous'
    st = client.get(f"/api/v1/recording/cameras/{cam['uuid']}/status", headers=h)
    assert st.json['data']['record_mode'] == 'continuous'


def test_manual_start_stop_protects(client, mock_go2rtc):
    h = login(client)
    cam = _create_camera(client, h)
    start = client.post(f"/api/v1/recording/cameras/{cam['uuid']}/manual/start", headers=h, json={'note': 't'})
    assert start.status_code == 200
    rid = start.json['data']['recording_id']
    assert client.get(f"/api/v1/recording/cameras/{cam['uuid']}/status", headers=h).json['data']['active_manual']
    stop = client.post(f"/api/v1/recording/cameras/{cam['uuid']}/manual/stop", headers=h, json={'recording_id': rid})
    assert stop.status_code == 200

    from server.model.recording import Recording
    rec = Recording.get_by_id(int(rid))
    assert rec.retention_class == 'protected' and rec.end_ts is not None


def test_recording_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _create_camera(client, h)
    create_user(client, h, 'rec_noscope', {'recordings': ['control'], 'cameras': ['read']})
    vh = login(client, 'rec_noscope', 'viewer1234!')
    assert client.put(f"/api/v1/recording/cameras/{cam['uuid']}/mode", headers=vh,
                      json={'mode': 'continuous'}).status_code == 403


# ── export ────────────────────────────────────────────────────────────────────
def test_export_create_and_list(client, mock_go2rtc, monkeypatch):
    h = login(client)
    cam = _create_camera(client, h)

    from server.task.list import transcode

    class FakeResult:
        id = 'fake-task-id'

    monkeypatch.setattr(transcode.run_export_job, 'delay', lambda *a, **k: FakeResult())

    end = utcnow()
    start = end - timedelta(minutes=2)
    r = client.post('/api/v1/export/jobs', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': to_epoch_ms(start), 'end_ts': to_epoch_ms(end), 'mode': 'copy'})
    assert r.status_code == 200 and r.json['data']['status'] == 'queued'
    job_id = r.json['data']['job_id']
    assert client.get(f'/api/v1/export/jobs/{job_id}', headers=h).status_code == 200
    assert client.get('/api/v1/export/jobs', headers=h).json['data']['pagination']['total'] >= 1


def test_export_rejects_bad_window(client, mock_go2rtc):
    h = login(client)
    cam = _create_camera(client, h)
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/export/jobs', headers=h,
                    json={'camera_uuid': cam['uuid'], 'start_ts': now, 'end_ts': now, 'mode': 'copy'})
    assert r.status_code == 400   # end <= start
