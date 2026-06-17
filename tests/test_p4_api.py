"""P4 HTTP surface: node join→heartbeat→assignments(etag/304)→ingest, detection search +
scope, zone/trigger/settings CRUD, and the full ingest→trigger→P3 object event→recording chain."""
from tests.conftest import create_user, login

CAMERA = {'name': 'AiCam', 'host': '192.0.2.40', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def _join_node(client, h, gpu=False, cap=4):
    cr = client.post('/api/v1/ai-nodes', headers=h, json={'name': 'node-test'})
    join_token = cr.json['data']['join_token']
    node = cr.json['data']['node']
    jr = client.post('/api/v1/ai/nodes/join', headers={'Authorization': 'Bearer ' + join_token},
                     json={'name': 'node-test', 'gpu': gpu, 'capacity': cap, 'capabilities': {'models': ['yolov8n']}})
    nh = {'Authorization': 'Bearer ' + jr.json['data']['node_token']}
    return node, nh


# ── node protocol ──────────────────────────────────────────────────────────────
def test_node_join_heartbeat_assignments(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    node, nh = _join_node(client, h)

    hb = client.post('/api/v1/ai/nodes/heartbeat', headers=nh, json={'status': 'online'})
    assert hb.status_code == 200 and 'assignments_etag' in hb.json['data']

    asg = client.get('/api/v1/ai/nodes/assignments', headers=nh)
    assert asg.status_code == 200
    items = asg.json['data']['items']
    assert any(str(s['camera_id']) == cam['id'] for s in items)        # camera assigned to this node
    spec = next(s for s in items if str(s['camera_id']) == cam['id'])
    assert spec['rtsp_url'].endswith(spec['go2rtc_name']) and spec['labels']

    etag = asg.json['data']['etag']
    asg304 = client.get('/api/v1/ai/nodes/assignments', headers={**nh, 'If-None-Match': etag})
    assert asg304.status_code == 304


def test_node_token_required(client, mock_go2rtc):
    # no node token → rejected
    assert client.post('/api/v1/ai/ingest/detections', json={'batch': []}).status_code == 401


def test_ingest_detections_and_search(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    _, nh = _join_node(client, h)
    ing = client.post('/api/v1/ai/ingest/detections', headers=nh, json={'batch': [
        {'camera_id': int(cam['id']), 'class_id': 0, 'confidence': 0.9, 'bbox': [0.1, 0.2, 0.3, 0.4], 'bytetrack_id': 5}]})
    assert ing.status_code == 200 and ing.json['data']['accepted'] == 1

    s = client.get('/api/v1/detections/search', headers=h, query_string={'label': 'person', 'group': 'raw'})
    assert s.status_code == 200 and s.json['data']['count'] >= 1


def test_ingest_rejects_unassigned_camera(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    _, nh = _join_node(client, h)
    other = client.post('/api/v1/cameras', headers=h, json={**CAMERA, 'name': 'Other', 'host': '192.0.2.41'}).json['data']
    # 'other' may be assigned too (rebalance); force a guaranteed-unassigned id
    ing = client.post('/api/v1/ai/ingest/detections', headers=nh, json={'batch': [
        {'camera_id': 999999999, 'class_id': 0, 'confidence': 0.9, 'bbox': [0, 0, 0.1, 0.1]}]})
    assert ing.json['data']['accepted'] == 0 and ing.json['data']['rejected'][0]['reason'] == 'not_assigned'


# ── detection search scope ──────────────────────────────────────────────────────
def test_detection_search_scope_denied(client, mock_go2rtc):
    h = login(client)
    _camera(client, h)
    create_user(client, h, 'det_noscope', {'detections': ['read']})
    vh = login(client, 'det_noscope', 'viewer1234!')
    r = client.get('/api/v1/detections/search', headers=vh)
    assert r.status_code == 200 and r.json['data']['count'] == 0


# ── zones / triggers / settings ─────────────────────────────────────────────────
def test_detection_zone_crud(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    cr = client.post(f"/api/v1/cameras/{cam['uuid']}/detection-zones", headers=h, json={
        'name': 'gate', 'kind': 'include', 'polygon': [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]})
    assert cr.status_code == 200, cr.json
    zid = cr.json['data']['id']
    lst = client.get(f"/api/v1/cameras/{cam['uuid']}/detection-zones", headers=h)
    assert any(z['id'] == zid for z in lst.json['data']['items'])
    up = client.put(f"/api/v1/detection-zones/{zid}", headers=h, json={'name': 'gate2'})
    assert up.status_code == 200 and up.json['data']['name'] == 'gate2'
    assert client.delete(f"/api/v1/detection-zones/{zid}", headers=h).status_code == 200


def test_detection_zone_rejects_bad_polygon(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/detection-zones", headers=h, json={
        'name': 'x', 'kind': 'include', 'polygon': [[0, 0], [1, 1]]})       # <3 points
    assert r.status_code == 400


def test_object_trigger_crud_and_test(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    cr = client.post('/api/v1/object-triggers', headers=h, json={
        'camera_uuid': cam['uuid'], 'name': 'person', 'labels': ['person'], 'min_confidence': 60})
    assert cr.status_code == 200, cr.json
    tid = cr.json['data']['id']
    assert client.post('/api/v1/object-triggers/test', headers=h, json={
        'camera_uuid': cam['uuid'], 'label': 'person', 'confidence': 80}).json['data']['matched'] is True
    assert client.post('/api/v1/object-triggers/test', headers=h, json={
        'camera_uuid': cam['uuid'], 'label': 'person', 'confidence': 50}).json['data']['matched'] is False
    assert client.delete(f'/api/v1/object-triggers/{tid}', headers=h).status_code == 200


def test_object_trigger_rejects_empty_labels(client, mock_go2rtc):
    h = login(client)
    r = client.post('/api/v1/object-triggers', headers=h, json={'name': 'x', 'labels': []})
    assert r.status_code == 400


def test_ai_settings_get_put(client, mock_go2rtc):
    h = login(client)
    g = client.get('/api/v1/ai/settings', headers=h)
    assert g.status_code == 200 and g.json['data']['global']['gpu_enabled'] is False
    up = client.put('/api/v1/ai/settings', headers=h, json={'gpu_enabled': True, 'model': 'yolov8s'})
    assert up.status_code == 200 and up.json['data']['gpu_enabled'] is True and up.json['data']['model'] == 'yolov8s'


def test_ai_nodes_requires_manage(client, mock_go2rtc):
    h = login(client)
    create_user(client, h, 'ai_noperm', {'detections': ['read']})
    vh = login(client, 'ai_noperm', 'viewer1234!')
    assert client.get('/api/v1/ai-nodes', headers=vh).status_code == 403


# ── full chain: ingest → trigger → P3 object event → recording ──────────────────
def test_ingest_trigger_creates_object_event_and_recording(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.post('/api/v1/event-policies', headers=h, json={
        'camera_uuid': cam['uuid'], 'event_type': 'object', 'action': 'record',
        'pre_buffer_s': 5, 'post_buffer_s': 10})
    client.post('/api/v1/object-triggers', headers=h, json={
        'camera_uuid': cam['uuid'], 'name': 'person', 'labels': ['person'], 'min_confidence': 50})
    _, nh = _join_node(client, h)

    ing = client.post('/api/v1/ai/ingest/detections', headers=nh, json={'batch': [
        {'camera_id': int(cam['id']), 'class_id': 0, 'confidence': 0.92, 'bbox': [0.4, 0.4, 0.6, 0.8], 'bytetrack_id': 9}]})
    assert ing.json['data']['accepted'] == 1

    ev = client.get('/api/v1/events', headers=h, query_string={'type': 'object'})
    assert ev.json['data']['count'] >= 1
    item = ev.json['data']['items'][0]
    assert item['type'] == 'object' and item['recording_id'] is not None
