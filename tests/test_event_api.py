"""P3 HTTP surface: simulate→event→clip, list scope, policy CRUD, schedule, timelapse."""
from datetime import timedelta

from server.model import to_epoch_ms, utcnow
from tests.conftest import create_user, login

CAMERA = {'name': 'Ev', 'host': '192.0.2.9', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


# ── simulate / list ───────────────────────────────────────────────────────────
def test_simulate_motion_creates_event_and_clip(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.post('/api/v1/events/simulate', headers=h,
                    json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 88})
    assert r.status_code == 200, r.json
    data = r.json['data']
    assert data['type'] == 'motion' and data['policy_action'] == 'record'
    assert data['recording_id'] is not None      # event clip materialized inline


def test_timeline_marker_carries_recording_id(client, mock_go2rtc):
    """Timeline markers expose recording_id so the client can snap a track click to the nearest
    PLAYABLE event clip (motion/intrusion), not notify-only noise like video_loss."""
    h = login(client)
    cam = _camera(client, h)
    ev = client.post('/api/v1/events/simulate', headers=h,
                     json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 80}).json['data']
    now = to_epoch_ms(utcnow())
    tl = client.get('/api/v1/events/timeline', headers=h, query_string={
        'camera_id': cam['uuid'], 'start': now - 3_600_000, 'end': now + 3_600_000})
    assert tl.status_code == 200, tl.json
    markers = tl.json['data']['markers']
    m = next((x for x in markers if x['event_id'] == ev['id']), None)
    assert m is not None and 'recording_id' in m
    assert m['recording_id'] == ev['recording_id']      # recorded motion event → playable marker


def test_simulate_unknown_type_rejected(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.post('/api/v1/events/simulate', headers=h,
                    json={'camera_uuid': cam['uuid'], 'type': 'nonsense'})
    assert r.status_code == 400


def test_list_events_and_scope(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.post('/api/v1/events/simulate', headers=h,
                json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 70})
    lst = client.get('/api/v1/events', headers=h)
    assert lst.status_code == 200 and lst.json['data']['count'] >= 1

    create_user(client, h, 'ev_noscope', {'events': ['read']})         # no camera_scope
    vh = login(client, 'ev_noscope', 'viewer1234!')
    res = client.get('/api/v1/events', headers=vh)
    assert res.status_code == 200 and res.json['data']['count'] == 0   # default-deny


def test_simulate_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'ev_sim', {'events': ['read', 'update']})   # perm but no camera scope
    vh = login(client, 'ev_sim', 'viewer1234!')
    res = client.post('/api/v1/events/simulate', headers=vh,
                      json={'camera_uuid': cam['uuid'], 'type': 'motion'})
    assert res.status_code == 403


# ── event policy CRUD ─────────────────────────────────────────────────────────
def test_event_policy_crud(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    cr = client.post('/api/v1/event-policies', headers=h, json={
        'camera_uuid': cam['uuid'], 'event_type': 'motion', 'action': 'record',
        'pre_buffer_s': 3, 'post_buffer_s': 7})
    assert cr.status_code == 200, cr.json
    pid = cr.json['data']['id']

    lst = client.get(f"/api/v1/event-policies?camera_id={cam['uuid']}", headers=h)
    assert any(p['id'] == pid for p in lst.json['data']['items'])

    up = client.put(f'/api/v1/event-policies/{pid}', headers=h, json={
        'event_type': 'motion', 'action': 'discard'})
    assert up.status_code == 200 and up.json['data']['action'] == 'discard'
    assert client.delete(f'/api/v1/event-policies/{pid}', headers=h).status_code == 200


def test_event_policy_rejects_bad_action(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.post('/api/v1/event-policies', headers=h, json={
        'camera_uuid': cam['uuid'], 'event_type': 'motion', 'action': 'bogus'})
    assert r.status_code == 400


# ── schedule ──────────────────────────────────────────────────────────────────
def test_schedule_get_and_replace(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    g0 = client.get(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h)
    assert g0.status_code == 200 and g0.json['data']['rules'] == []

    pr = client.put(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h, json={
        'rules': [{'day_of_week': 0, 'start_min': 540, 'end_min': 1080, 'mode': 'event', 'priority': 5}]})
    assert pr.status_code == 200 and len(pr.json['data']['rules']) == 1
    g1 = client.get(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h)
    assert g1.json['data']['rules'][0]['mode'] == 'event'


def test_schedule_rejects_bad_rule(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    bad = client.put(f"/api/v1/cameras/{cam['uuid']}/schedule", headers=h, json={
        'rules': [{'day_of_week': 9, 'start_min': 0, 'end_min': 100, 'mode': 'event'}]})
    assert bad.status_code == 400


# ── timelapse ─────────────────────────────────────────────────────────────────
def test_timelapse_create_and_get(client, mock_go2rtc, monkeypatch):
    h = login(client)
    cam = _camera(client, h)
    from server.task.list import timelapse as tl

    class FakeResult:
        id = 'fake-tl-task'

    monkeypatch.setattr(tl.run_timelapse, 'delay', lambda *a, **k: FakeResult())

    end = utcnow()
    start = end - timedelta(hours=1)
    r = client.post('/api/v1/timelapse', headers=h, json={
        'camera_uuid': cam['uuid'], 'range_start': to_epoch_ms(start),
        'range_end': to_epoch_ms(end), 'speed_factor': 60})
    assert r.status_code == 200, r.json
    assert r.json['data']['status'] == 'queued'
    job_id = r.json['data']['id']
    assert client.get(f'/api/v1/timelapse/{job_id}', headers=h).status_code == 200


def test_timelapse_rejects_bad_range(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/timelapse', headers=h, json={
        'camera_uuid': cam['uuid'], 'range_start': now, 'range_end': now, 'speed_factor': 60})
    assert r.status_code == 400      # end <= start
