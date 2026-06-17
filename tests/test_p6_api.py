"""P6 Wave 1 — feature flags + bookmarks (R2). Flag gate, RBAC, camera scope,
lock_retention → P2 protected recording."""
from server.model import to_epoch_ms, utcnow
from tests.conftest import create_user, login

CAMERA = {'name': 'Bm', 'host': '192.0.2.21', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


# ── feature flags ─────────────────────────────────────────────────────────────
def test_feature_flags_seeded_and_readable(client):
    h = login(client)
    r = client.get('/api/v1/feature-flags', headers=h)
    assert r.status_code == 200, r.json
    data = r.json['data']
    assert data['enabled']['bookmarks'] is True            # Wave 1 ships ON
    assert data['enabled']['semantic_search'] is True      # A1 implemented (pluggable embedder)
    assert data['enabled']['two_way_audio'] is True        # L1 implemented
    assert data['enabled']['maps'] is True                 # always-on now (hidden from list)
    assert data['enabled']['doorbell'] is True
    keys = {f['key'] for f in data['items']}
    assert {'semantic_search', 'share_links'} <= keys       # genuinely-global flags still listed
    # always-on / config-driven / per-dashboard → hidden from the toggle list
    assert not ({'bookmarks', 'two_way_audio', 'access_control',
                 'maps', 'doorbell', 'batch_camera_add', 'live_sequence', 'remote_portal'} & keys)


def test_feature_flag_toggle_admin_only(client):
    h = login(client)
    off = client.put('/api/v1/feature-flags/bookmarks', headers=h, json={'enabled': False})
    assert off.status_code == 200 and off.json['data']['enabled'] is False
    assert client.get('/api/v1/feature-flags', headers=h).json['data']['enabled']['bookmarks'] is False

    create_user(client, h, 'ff_user', {'bookmarks': ['read', 'update']})  # no feature_flags perm
    vh = login(client, 'ff_user', 'viewer1234!')
    assert client.get('/api/v1/feature-flags', headers=vh).status_code == 200      # read allowed
    denied = client.put('/api/v1/feature-flags/bookmarks', headers=vh, json={'enabled': True})
    assert denied.status_code == 403


def test_feature_flag_unknown_rejected(client):
    h = login(client)
    assert client.put('/api/v1/feature-flags/does_not_exist', headers=h, json={'enabled': True}).status_code == 400


# ── bookmarks CRUD ────────────────────────────────────────────────────────────
def test_bookmark_crud(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())

    cr = client.post('/api/v1/bookmarks', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': now, 'label': '택배 도착', 'color': '#EF4444'})
    assert cr.status_code == 200, cr.json
    bid = cr.json['data']['id']
    assert cr.json['data']['label'] == '택배 도착'

    lst = client.get(f"/api/v1/bookmarks?camera_uuid={cam['uuid']}&start={now - 1000}&end={now + 1000}", headers=h)
    assert lst.status_code == 200 and lst.json['data']['count'] == 1

    up = client.put(f'/api/v1/bookmarks/{bid}', headers=h, json={'label': '수정됨'})
    assert up.status_code == 200 and up.json['data']['label'] == '수정됨'

    assert client.delete(f'/api/v1/bookmarks/{bid}', headers=h).status_code == 200
    gone = client.get(f"/api/v1/bookmarks?camera_uuid={cam['uuid']}", headers=h)
    assert gone.json['data']['count'] == 0


def test_bookmark_requires_label_and_start(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    assert client.post('/api/v1/bookmarks', headers=h,
                       json={'camera_uuid': cam['uuid'], 'start_ts': to_epoch_ms(utcnow())}).status_code == 400
    assert client.post('/api/v1/bookmarks', headers=h,
                       json={'camera_uuid': cam['uuid'], 'label': 'x'}).status_code == 400


def test_bookmark_feature_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/bookmarks', headers=h, json={'enabled': False})
    blocked = client.post('/api/v1/bookmarks', headers=h,
                          json={'camera_uuid': cam['uuid'], 'start_ts': to_epoch_ms(utcnow()), 'label': 'x'})
    assert blocked.status_code == 403          # flag off → feature_disabled


def test_bookmark_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'bm_user', {'bookmarks': ['read', 'update']})  # perm but no camera scope
    vh = login(client, 'bm_user', 'viewer1234!')
    res = client.post('/api/v1/bookmarks', headers=vh,
                      json={'camera_uuid': cam['uuid'], 'start_ts': to_epoch_ms(utcnow()), 'label': 'x'})
    assert res.status_code == 403


def test_bookmark_lock_retention_protects_recording(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    # simulate motion → materializes an event clip (recording)
    ev = client.post('/api/v1/events/simulate', headers=h,
                     json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 90}).json['data']
    rec_id = ev['recording_id']
    assert rec_id

    client.post('/api/v1/bookmarks', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': ev['start_ts'], 'label': '증거',
        'recording_id': rec_id, 'lock_retention': True})

    from server.model import db
    from server.model.recording import CLASS_PROTECTED, Recording
    rec = db.session.query(Recording).filter(Recording.id == int(rec_id)).first()
    assert rec.retention_class == CLASS_PROTECTED
