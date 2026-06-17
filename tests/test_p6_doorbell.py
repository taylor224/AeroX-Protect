"""P6 M3 — doorbell ring → doorbell_call event."""
from tests.conftest import create_user, login

CAMERA = {'name': 'Door', 'host': '192.0.2.190', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def test_doorbell_ring_creates_event(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/doorbell", headers=h, json={})
    assert r.status_code == 200, r.json
    assert r.json['data']['event_id']
    ev = client.get('/api/v1/events?type=doorbell_call', headers=h)
    assert ev.status_code == 200 and ev.json['data']['count'] >= 1


def test_doorbell_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/doorbell', headers=h, json={'enabled': False})
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/doorbell", headers=h, json={}).status_code == 403


def test_doorbell_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'door_u', {'events': ['update']})   # perm, no camera scope
    vh = login(client, 'door_u', 'viewer1234!')
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/doorbell", headers=vh, json={}).status_code == 403
