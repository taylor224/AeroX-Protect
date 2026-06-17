"""Regression tests for the security-audit pass (authz/IDOR/SSRF/injection/CORS).

Covers:
- IDOR: recording.protect / schedule / ai-settings / timelapse-list enforce camera scope
- SSRF: federation guard reuses the hardened webhook policy (metadata always blocked)
- external subscription camera_ids clamped to the token's scope
- go2rtc source-string injection rejected in camera host / rtsp_path
- CORS: wildcard origin does not get credentialed reflection
"""
from server.model.api_token import ApiToken
from tests.conftest import create_user, login

CAMERA = {'name': 'Sec', 'host': '192.0.2.10', 'vendor': 'onvif', 'driver': 'onvif',
          'streams': [{'role': 'main', 'rtsp_path': '/stream1'}]}


def _camera(client, h, **over):
    body = {**CAMERA, **over}
    r = client.post('/api/v1/cameras', headers=h, json=body)
    assert r.status_code == 200, r.json
    return r.json['data']


def _scoped_user(client, h, login_id, perms, camera_uuid, actions=('view',)):
    """Create a non-superuser with global perms + camera_scope over exactly one camera."""
    perms = {**perms, 'camera_scope': {camera_uuid: list(actions)}}
    create_user(client, h, login_id, perms)
    return login(client, login_id, 'viewer1234!')


# ── IDOR: recording.protect must be camera-scoped ─────────────────────────────
def test_recording_protect_idor_blocked(client, mock_go2rtc):
    from server.model.recording import CLASS_EVENT, Recording
    h = login(client)
    cam_a = _camera(client, h, host='192.0.2.11')
    cam_b = _camera(client, h, host='192.0.2.12')
    from server.model import utcnow
    from server.model.camera import Camera
    cam_b_id = Camera.get_by_uuid(cam_b['uuid']).id
    rec = Recording.create(cam_b_id, 'event', CLASS_EVENT, utcnow(), end_ts=None)

    uh = _scoped_user(client, h, 'rec_op', {'recordings': ['control']}, cam_a['uuid'])
    r = client.post('/api/v1/recording/recordings/%s/protect' % rec.id, headers=uh,
                    json={'protected': False})
    assert r.status_code == 403                        # cannot touch camera B's recording

    # superuser still can
    assert client.post('/api/v1/recording/recordings/%s/protect' % rec.id, headers=h,
                       json={'protected': True}).status_code == 200


# ── IDOR: schedule read/write must be camera-scoped ───────────────────────────
def test_schedule_idor_blocked(client, mock_go2rtc):
    h = login(client)
    cam_a = _camera(client, h, host='192.0.2.13')
    cam_b = _camera(client, h, host='192.0.2.14')
    uh = _scoped_user(client, h, 'sched_op', {'schedules': ['read', 'update']}, cam_a['uuid'])

    assert client.get('/api/v1/cameras/%s/schedule' % cam_b['uuid'], headers=uh).status_code == 403
    r = client.put('/api/v1/cameras/%s/schedule' % cam_b['uuid'], headers=uh,
                   json={'rules': [{'day_of_week': 1, 'start_min': 0, 'end_min': 60, 'mode': 'continuous'}]})
    assert r.status_code == 403
    # in-scope camera works
    assert client.get('/api/v1/cameras/%s/schedule' % cam_a['uuid'], headers=uh).status_code == 200

    # apply-group silently skips out-of-scope cameras
    r = client.post('/api/v1/schedules/apply-group', headers=uh, json={
        'rules': [{'day_of_week': 1, 'start_min': 0, 'end_min': 60, 'mode': 'continuous'}],
        'camera_ids': [cam_a['uuid'], cam_b['uuid']]})
    assert r.status_code == 200 and r.json['data']['applied'] == 1


# ── IDOR: per-camera AI settings must be camera-scoped ────────────────────────
def test_ai_settings_idor_blocked(client, mock_go2rtc):
    h = login(client)
    cam_a = _camera(client, h, host='192.0.2.15')
    cam_b = _camera(client, h, host='192.0.2.16')
    uh = _scoped_user(client, h, 'ai_op', {'ai': ['read', 'update']}, cam_a['uuid'])

    assert client.get('/api/v1/ai/settings?camera_id=%s' % cam_b['uuid'], headers=uh).status_code == 403
    r = client.put('/api/v1/cameras/%s/ai-settings' % cam_b['uuid'], headers=uh, json={'target_fps': 1})
    assert r.status_code == 403
    assert client.get('/api/v1/ai/settings?camera_id=%s' % cam_a['uuid'], headers=uh).status_code == 200


# ── IDOR: timelapse listing must be scoped / superuser for all ────────────────
def test_timelapse_list_requires_scope(client, mock_go2rtc):
    h = login(client)
    cam_a = _camera(client, h, host='192.0.2.17')
    cam_b = _camera(client, h, host='192.0.2.18')
    uh = _scoped_user(client, h, 'tl_op', {'timelapse': ['read']}, cam_a['uuid'])

    assert client.get('/api/v1/timelapse?camera_id=%s' % cam_b['uuid'], headers=uh).status_code == 403
    assert client.get('/api/v1/timelapse', headers=uh).status_code == 403        # all-cameras: superuser only
    assert client.get('/api/v1/timelapse?camera_id=%s' % cam_a['uuid'], headers=uh).status_code == 200
    assert client.get('/api/v1/timelapse', headers=h).status_code == 200         # superuser sees all


# ── go2rtc source-string injection rejected ───────────────────────────────────
def test_camera_host_injection_rejected(client, mock_go2rtc):
    h = login(client)
    r = client.post('/api/v1/cameras', headers=h,
                    json={**CAMERA, 'host': '192.0.2.9#exec=/bin/sh'})
    assert r.status_code == 400
    r = client.post('/api/v1/cameras', headers=h,
                    json={**CAMERA, 'host': '192.0.2.9', 'streams': [{'role': 'main', 'rtsp_path': '/s#video=copy'}]})
    assert r.status_code == 400


# ── federation SSRF reuses hardened policy ────────────────────────────────────
def test_federation_guard_blocks_metadata(app_db, monkeypatch):
    from server.driver import federation as drv
    monkeypatch.setattr('config.WEBHOOK_ALLOW_PRIVATE', True)   # even with LAN opt-in
    c = drv.FederationClient('http://169.254.169.254', 'tok')
    try:
        c.state()
        assert False
    except drv.FederationError as e:
        assert 'blocked' in str(e)


def test_federation_refuses_redirect(monkeypatch):
    from types import SimpleNamespace

    from server.driver import federation as drv
    monkeypatch.setattr(drv, '_guard_url', lambda url: None)
    monkeypatch.setattr(drv.requests, 'get',
                        lambda *a, **k: SimpleNamespace(status_code=302, is_redirect=True, json=lambda: {}))
    c = drv.FederationClient('https://m.example.com', 'tok')
    try:
        c.state()
        assert False
    except drv.FederationError as e:
        assert 'redirect' in str(e)


# ── external subscription camera_ids clamped to token scope ───────────────────
def test_ext_subscription_clamps_camera_scope(app_db):
    from server.controller.external import ExternalController
    from server.model.webhook_endpoint import WebhookEndpoint
    tok, _ = ApiToken.issue('scoped', {'events': ['read']}, camera_ids=[5])
    # requesting cameras 5 (in scope) and 9 (out) → stored filter keeps only 5
    res = ExternalController.create_subscription(tok, {'url': 'https://hook.example.com',
                                                       'camera_ids': [5, 9]})
    hook = WebhookEndpoint.get_by_uuid(res['uuid'])
    assert hook.subscription_filter['camera_ids'] == [5]

    # entirely out-of-scope → rejected
    import pytest
    from server.exception import InvalidParameterException
    with pytest.raises(InvalidParameterException):
        ExternalController.create_subscription(tok, {'url': 'https://h2.example.com', 'camera_ids': [9]})


def test_ext_delivery_respects_token_scope(app_db, monkeypatch):
    from server.controller.external import ExternalController
    tok, _ = ApiToken.issue('deliv', {'events': ['read']}, camera_ids=[5])
    ExternalController.create_subscription(tok, {'url': 'https://hook.example.com', 'camera_ids': [5]})
    sent = []
    monkeypatch.setattr('server.driver.webhook.deliver',
                        lambda hook, payload: sent.append(payload) or {'status': 'success'})
    ExternalController.deliver_subscriptions({'type': 'motion', 'camera_id': '9'})   # out of scope
    assert sent == []
    ExternalController.deliver_subscriptions({'type': 'motion', 'camera_id': '5'})   # in scope
    assert len(sent) == 1


# ── CORS: wildcard origin is not credentialed-reflected ───────────────────────
def test_cors_wildcard_no_credentialed_reflection(client):
    r = client.get('/api/v1/auth/login', headers={'Origin': 'https://evil.example.com'})
    acao = r.headers.get('Access-Control-Allow-Origin')
    acac = r.headers.get('Access-Control-Allow-Credentials')
    # must NOT both reflect the attacker origin AND allow credentials
    assert not (acao == 'https://evil.example.com' and acac == 'true')
