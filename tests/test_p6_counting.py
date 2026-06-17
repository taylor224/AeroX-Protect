"""P6 A2/A3 — counting lines (in/out, occupancy) + loitering."""
from datetime import datetime, timedelta

from server.model import to_epoch_ms
from tests.conftest import create_user, login

CAMERA = {'name': 'Cnt', 'host': '192.0.2.150', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}
REGION = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def _row(cam_id, ts, track, bbox, label='person'):
    return {'camera_id': cam_id, 'ts': ts, 'track_id': track, 'bbox': bbox, 'label': label}


def test_counting_line_crud(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    cr = client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h, json={
        'name': '정문', 'kind': 'line', 'geometry': [[0.5, 0.0], [0.5, 1.0]], 'class_filter': ['person']})
    assert cr.status_code == 200, cr.json
    lid = cr.json['data']['id']
    assert cr.json['data']['kind'] == 'line'
    assert len(client.get(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h).json['data']['items']) == 1
    up = client.put(f'/api/v1/counting/{lid}', headers=h, json={'enabled': False})
    assert up.json['data']['enabled'] is False
    assert client.delete(f'/api/v1/counting/{lid}', headers=h).status_code == 200


def test_counting_validation(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h,
                       json={'name': 'x', 'kind': 'line', 'geometry': [[0.5, 0]]}).status_code == 400
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h,
                       json={'name': 'x', 'kind': 'region', 'geometry': [[0.1, 0.1], [0.2, 0.2]]}).status_code == 400


def test_line_crossing_counts(client, mock_go2rtc):
    from server.service import counting
    h = login(client)
    cam = _camera(client, h)
    client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h,
                json={'name': 'gate', 'kind': 'line', 'geometry': [[0.5, 0.0], [0.5, 1.0]]})
    cam_id = int(cam['id'])
    ts = datetime(2026, 1, 1, 12, 0, 0)
    counting.process_batch(cam_id, [_row(cam_id, ts, 7, [0.1, 0.1, 0.3, 0.5])])   # left of line
    counting.process_batch(cam_id, [_row(cam_id, ts, 7, [0.6, 0.1, 0.8, 0.5])])   # crossed to right

    now = to_epoch_ms(ts)
    r = client.get(f"/api/v1/analytics/counting?camera_id={cam['uuid']}&start={now - 60000}&end={now + 60000}", headers=h)
    items = r.json['data']['items']
    assert items and (items[0]['in_count'] + items[0]['out_count']) >= 1


def test_loitering_emits_event(client, mock_go2rtc):
    from server.service import counting
    h = login(client)
    cam = _camera(client, h)
    client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h, json={
        'name': '로비', 'kind': 'region', 'geometry': REGION, 'loiter_threshold_s': 5})
    cam_id = int(cam['id'])
    inside = [0.4, 0.4, 0.6, 0.6]   # bottom-center (0.5, 0.6) inside REGION
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    counting.process_batch(cam_id, [_row(cam_id, t0, 9, inside)])                       # enters
    counting.process_batch(cam_id, [_row(cam_id, t0 + timedelta(seconds=6), 9, inside)])  # dwell ≥ 5 → loitering

    ev = client.get('/api/v1/events?type=loitering', headers=h)
    assert ev.status_code == 200 and ev.json['data']['count'] >= 1


def test_counting_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/object_counting', headers=h, json={'enabled': False})
    client.put('/api/v1/feature-flags/loitering', headers=h, json={'enabled': False})
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=h,
                       json={'name': 'x', 'kind': 'line', 'geometry': [[0.5, 0], [0.5, 1]]}).status_code == 403


def test_counting_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'cnt_u', {'ai': ['count']})   # perm, no camera scope
    vh = login(client, 'cnt_u', 'viewer1234!')
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/counting", headers=vh,
                       json={'name': 'x', 'kind': 'line', 'geometry': [[0.5, 0], [0.5, 1]]}).status_code == 403
