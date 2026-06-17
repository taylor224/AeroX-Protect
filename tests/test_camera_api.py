from tests.conftest import create_user, login

CAMERA = {
    'name': 'Front', 'host': '192.168.1.50', 'vendor': 'hikvision', 'driver': 'isapi',
    'rtsp_port': 554, 'channel': 1, 'username': 'admin', 'password': 'secret',
    'ptz_supported': True,
    'streams': [
        {'role': 'main', 'codec': 'h265', 'width': 3840, 'height': 2160, 'fps': 20,
         'rtsp_path': '/Streaming/Channels/101'},
        {'role': 'sub', 'codec': 'h264', 'width': 704, 'height': 480, 'fps': 15,
         'rtsp_path': '/Streaming/Channels/102'},
    ],
}


def _create(client, headers, **over):
    payload = {**CAMERA, **over}
    return client.post('/api/v1/cameras', headers=headers, json=payload)


def test_camera_create_does_not_leak_credentials(client, mock_go2rtc):
    h = login(client)
    r = _create(client, h)
    assert r.status_code == 200, r.json
    data = r.json['data']
    assert data['has_credentials'] is True
    body = str(r.json)
    assert 'secret' not in body and 'password_enc' not in body and 'username_enc' not in body


def test_camera_crud_and_streams(client, mock_go2rtc):
    h = login(client)
    uuid = _create(client, h).json['data']['uuid']

    data = client.get(f'/api/v1/cameras/{uuid}', headers=h).json['data']
    assert len(data['streams']) == 2
    names = {s['go2rtc_name'] for s in data['streams']}
    assert ('cam_%s_main' % uuid) in names and ('cam_%s_sub' % uuid) in names
    # sub is the default-live stream
    sub = next(s for s in data['streams'] if s['role'] == 'sub')
    assert sub['is_default_live'] is True

    lst = client.get('/api/v1/cameras?page=1&items_per_page=20', headers=h)
    assert lst.json['data']['pagination']['total'] == 1

    upd = client.post(f'/api/v1/cameras/{uuid}', headers=h, json={'name': 'Front Door'})
    assert upd.json['data']['name'] == 'Front Door'

    assert client.delete(f'/api/v1/cameras/{uuid}', headers=h).status_code == 200
    assert client.get(f'/api/v1/cameras/{uuid}', headers=h).status_code == 404


def test_camera_duplicate_serial_conflicts(client, mock_go2rtc):
    h = login(client)
    assert _create(client, h, serial='SN-DUP', streams=[]).status_code == 200
    assert _create(client, h, serial='SN-DUP', host='10.9.9.9', streams=[]).status_code == 409


def test_camera_credentials_roundtrip_in_db(client, mock_go2rtc):
    h = login(client)
    uuid = _create(client, h).json['data']['uuid']
    from server.model.camera import Camera
    cam = Camera.get_by_uuid(uuid)
    assert cam.get_credentials() == ('admin', 'secret')   # decrypts correctly


def test_camera_requires_permission(client, mock_go2rtc):
    h = login(client)
    create_user(client, h, 'noaccess', {'live': ['read']})
    vh = login(client, 'noaccess', 'viewer1234!')
    assert client.get('/api/v1/cameras', headers=vh).status_code == 403


def test_snapshot_scope_denied(client, mock_go2rtc):
    h = login(client)
    uuid = _create(client, h, streams=[{'role': 'sub', 'rtsp_path': '/p'}]).json['data']['uuid']
    # has live:read + cameras:read but NO camera_scope -> default deny
    create_user(client, h, 'liveonly', {'live': ['read'], 'cameras': ['read']})
    vh = login(client, 'liveonly', 'viewer1234!')
    assert client.get(f'/api/v1/cameras/{uuid}/snapshot', headers=vh).status_code == 403


def test_ptz_scope_denied(client, mock_go2rtc):
    h = login(client)
    uuid = _create(client, h).json['data']['uuid']
    # ptz:control but no camera_scope -> denied
    create_user(client, h, 'ptzonly', {'ptz': ['control'], 'cameras': ['read']})
    vh = login(client, 'ptzonly', 'viewer1234!')
    assert client.post(f'/api/v1/cameras/{uuid}/ptz', headers=vh, json={'action': 'stop'}).status_code == 403


def test_ptz_validation_and_execute(client, mock_go2rtc, monkeypatch):
    h = login(client)
    uuid = _create(client, h).json['data']['uuid']
    from types import SimpleNamespace

    from server.controller import ptz as ptz_ctrl
    fake = SimpleNamespace(ptz_continuous=lambda *a, **k: None, ptz_stop=lambda: None)
    monkeypatch.setattr(ptz_ctrl, '_driver_for', lambda camera: fake)

    bad = client.post(f'/api/v1/cameras/{uuid}/ptz', headers=h,
                      json={'action': 'continuous', 'pan': 2.0, 'tilt': 0, 'zoom': 0})
    assert bad.status_code == 400   # pan out of [-1,1]
    ok = client.post(f'/api/v1/cameras/{uuid}/ptz', headers=h, json={'action': 'stop'})
    assert ok.status_code == 200
