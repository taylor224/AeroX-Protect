"""P6 Wave 1 — M1 batch camera add + R1 share links."""
from server.model import to_epoch_ms, utcnow
from tests.conftest import create_user, login

CAMERA = {'name': 'Sh', 'host': '192.0.2.40', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}
COMMON = {'vendor': 'onvif', 'driver': 'onvif', 'rtsp_port': 554, 'username': 'admin',
          'password': 'secret', 'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h, host='192.0.2.40'):
    return client.post('/api/v1/cameras', headers=h, json={**CAMERA, 'host': host}).json['data']


# ── M1 batch camera add ───────────────────────────────────────────────────────
def test_batch_camera_add(client, mock_go2rtc):
    h = login(client)
    body = {'common': COMMON, 'items': [
        {'name': 'Cam A', 'host': '192.0.2.51'},
        {'name': 'Cam B', 'host': '192.0.2.52'},
        {'name': 'Cam C', 'host': '192.0.2.53'}]}
    r = client.post('/api/v1/cameras/batch', headers=h, json=body)
    assert r.status_code == 200, r.json
    d = r.json['data']
    assert d['created'] == 3 and d['failed'] == 0
    assert len(client.get('/api/v1/cameras', headers=h).json['data']['items']) == 3


def test_batch_partial_failure_does_not_abort(client, mock_go2rtc):
    h = login(client)
    body = {'common': COMMON, 'items': [
        {'name': 'Cam A', 'host': '192.0.2.61'},
        {'name': 'Dup', 'host': '192.0.2.61'},   # same host+channel → conflict
        {'name': 'NoHost'}]}                       # missing host → invalid
    r = client.post('/api/v1/cameras/batch', headers=h, json=body)
    d = r.json['data']
    assert d['created'] == 1 and d['failed'] == 2
    statuses = {x['status'] for x in d['results']}
    assert statuses == {'created', 'failed'}


def test_batch_feature_flag_gate(client, mock_go2rtc):
    h = login(client)
    client.put('/api/v1/feature-flags/batch_camera_add', headers=h, json={'enabled': False})
    r = client.post('/api/v1/cameras/batch', headers=h,
                    json={'common': COMMON, 'items': [{'name': 'X', 'host': '192.0.2.71'}]})
    assert r.status_code == 400      # feature_disabled


# ── R1 share links ────────────────────────────────────────────────────────────
def test_share_clip_create_and_public_view(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    cr = client.post('/api/v1/share-links', headers=h, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 60_000, 'range_end': now})
    assert cr.status_code == 200, cr.json
    token = cr.json['data']['token']
    assert token and cr.json['data']['path'] == f'/s/{token}'

    # public viewer — NO auth header
    v = client.get(f'/api/v1/s/{token}')
    assert v.status_code == 200, v.json
    assert v.json['data']['status'] == 'ok'
    assert v.json['data']['camera_name'] == cam['name']
    assert isinstance(v.json['data']['segments'], list)   # empty (no recordings) is fine


def test_share_password_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    token = client.post('/api/v1/share-links', headers=h, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 1000, 'range_end': now,
        'password': 's3cret'}).json['data']['token']

    assert client.get(f'/api/v1/s/{token}').json['data']['status'] == 'password_required'
    assert client.post(f'/api/v1/s/{token}', json={'password': 'wrong'}).json['data']['status'] == 'password_required'
    ok = client.post(f'/api/v1/s/{token}', json={'password': 's3cret'})
    assert ok.json['data']['status'] == 'ok'


def test_share_max_views_and_revoke(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    created = client.post('/api/v1/share-links', headers=h, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 1000, 'range_end': now,
        'max_views': 1}).json['data']
    token, sid = created['token'], created['id']

    assert client.get(f'/api/v1/s/{token}').json['data']['status'] == 'ok'        # view 1
    assert client.get(f'/api/v1/s/{token}').json['data']['status'] == 'exhausted'  # view 2 over cap

    # revoke a fresh link
    c2 = client.post('/api/v1/share-links', headers=h, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 1000, 'range_end': now}).json['data']
    assert client.delete(f"/api/v1/share-links/{c2['id']}", headers=h).status_code == 200
    assert client.get(f"/api/v1/s/{c2['token']}").json['data']['status'] == 'revoked'
    assert sid  # created had an id


def test_share_event_link(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    ev = client.post('/api/v1/events/simulate', headers=h,
                     json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 80}).json['data']
    cr = client.post('/api/v1/share-links', headers=h, json={'kind': 'event', 'event_id': ev['id']})
    assert cr.status_code == 200, cr.json
    v = client.get(f"/api/v1/s/{cr.json['data']['token']}")
    assert v.json['data']['status'] == 'ok' and v.json['data']['is_event'] is True


def test_share_invalid_token_404(client):
    assert client.get('/api/v1/s/nonexistent-token').status_code == 404


def test_share_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'sh_user', {'share': ['create']})   # perm but no camera scope
    vh = login(client, 'sh_user', 'viewer1234!')
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/share-links', headers=vh, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 1000, 'range_end': now})
    assert r.status_code == 403


def test_share_feature_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/share_links', headers=h, json={'enabled': False})
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/share-links', headers=h, json={
        'kind': 'clip', 'camera_uuid': cam['uuid'], 'range_start': now - 1000, 'range_end': now})
    assert r.status_code == 403
