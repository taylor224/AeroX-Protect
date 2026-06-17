"""P6 L6 — maps + camera markers."""
from tests.conftest import create_user, login

CAMERA = {'name': 'MapCam', 'host': '192.0.2.130', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def test_map_crud(client):
    h = login(client)
    cr = client.post('/api/v1/maps', headers=h, json={
        'name': '본관', 'kind': 'geo', 'config': {'center_lat': 37.5, 'center_lng': 127.0, 'zoom': 16}})
    assert cr.status_code == 200, cr.json
    mid = cr.json['data']['id']
    assert cr.json['data']['kind'] == 'geo'
    assert len(client.get('/api/v1/maps', headers=h).json['data']['items']) == 1
    up = client.put(f'/api/v1/maps/{mid}', headers=h, json={'name': '주차장'})
    assert up.json['data']['name'] == '주차장'
    assert client.delete(f'/api/v1/maps/{mid}', headers=h).status_code == 200
    assert client.get('/api/v1/maps', headers=h).json['data']['items'] == []


def test_map_markers_replace(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    mid = client.post('/api/v1/maps', headers=h, json={'name': 'm', 'kind': 'geo'}).json['data']['id']
    cam_id = cam['id']
    r = client.put(f'/api/v1/maps/{mid}/markers', headers=h, json={'markers': [
        {'camera_id': cam_id, 'x': 127.02, 'y': 37.51, 'label': '현관'}]})
    assert r.status_code == 200, r.json
    markers = r.json['data']['markers']
    assert len(markers) == 1 and markers[0]['label'] == '현관'
    # get returns markers too
    got = client.get(f'/api/v1/maps/{mid}', headers=h).json['data']
    assert len(got['markers']) == 1
    # replace with empty clears
    client.put(f'/api/v1/maps/{mid}/markers', headers=h, json={'markers': []})
    assert client.get(f'/api/v1/maps/{mid}', headers=h).json['data']['markers'] == []


def test_map_marker_validation(client):
    h = login(client)
    mid = client.post('/api/v1/maps', headers=h, json={'name': 'm'}).json['data']['id']
    bad = client.put(f'/api/v1/maps/{mid}/markers', headers=h, json={'markers': [{'x': 1, 'y': 2}]})
    assert bad.status_code == 400   # missing camera_id


def test_map_flag_gate(client):
    h = login(client)
    client.put('/api/v1/feature-flags/maps', headers=h, json={'enabled': False})
    assert client.post('/api/v1/maps', headers=h, json={'name': 'x'}).status_code == 403


def test_map_requires_permission(client):
    h = login(client)
    create_user(client, h, 'map_u', {'maps': ['read']})   # read only
    vh = login(client, 'map_u', 'viewer1234!')
    assert client.get('/api/v1/maps', headers=vh).status_code == 200
    assert client.post('/api/v1/maps', headers=vh, json={'name': 'x'}).status_code == 403


def test_map_config_provider_and_key(client):
    h = login(client)
    # default provider is OSM, no key
    cfg = client.get('/api/v1/maps/config', headers=h)
    assert cfg.status_code == 200
    assert cfg.json['data']['provider'] == 'osm' and cfg.json['data']['has_key'] is False

    # switch to google + set a client key; key is returned (client SDK needs it) but stored encrypted
    up = client.put('/api/v1/maps/config', headers=h, json={'provider': 'google', 'google_api_key': 'AIzaTEST123'})
    assert up.status_code == 200
    assert up.json['data']['provider'] == 'google'
    assert up.json['data']['has_key'] is True and up.json['data']['google_api_key'] == 'AIzaTEST123'

    from server.model.map_config import MapConfig
    assert MapConfig.get().google_api_key_enc is not None      # encrypted at rest (not plaintext)

    # clearing the key
    cl = client.put('/api/v1/maps/config', headers=h, json={'provider': 'osm', 'google_api_key': ''})
    assert cl.json['data']['has_key'] is False and cl.json['data']['provider'] == 'osm'


def test_map_config_write_requires_update_permission(client):
    h = login(client)
    create_user(client, h, 'map_ro', {'maps': ['read']})
    vh = login(client, 'map_ro', 'viewer1234!')
    assert client.get('/api/v1/maps/config', headers=vh).status_code == 200      # read ok
    assert client.put('/api/v1/maps/config', headers=vh,
                      json={'provider': 'google'}).status_code == 403            # write denied
