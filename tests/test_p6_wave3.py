"""P6 Wave 3 — L5 fisheye config + L7 ffmpeg HW decode."""
from tests.conftest import login

CAMERA = {'name': 'Fish', 'host': '192.0.2.170', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def test_camera_fisheye_config(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    assert cam['fisheye'] is False
    up = client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={
        'fisheye': True, 'fisheye_params': {'cx': 0.5, 'cy': 0.5, 'radius': 0.48, 'mode': 'panorama'}})
    assert up.status_code == 200, up.json
    got = client.get(f"/api/v1/cameras/{cam['uuid']}", headers=h).json['data']
    assert got['fisheye'] is True and got['fisheye_params']['mode'] == 'panorama'


def test_ai_settings_hwaccel(client, mock_go2rtc):
    h = login(client)
    up = client.put('/api/v1/ai/settings', headers=h, json={'hwaccel': 'vaapi'})
    assert up.status_code == 200, up.json
    assert up.json['data']['hwaccel'] == 'vaapi'


def test_ffmpeg_hwaccel_in_reencode_cmds(client, mock_go2rtc):
    from server.service import ffmpeg
    h = login(client)
    # default 'none' → no -hwaccel
    assert '-hwaccel' not in ffmpeg.build_transcode_cmd('l.txt', 'o.mp4', 0, 10, 720)
    assert '-hwaccel' not in ffmpeg.build_timelapse_cmd('l.txt', 'o.mp4', 4)

    client.put('/api/v1/ai/settings', headers=h, json={'hwaccel': 'cuda'})
    cmd = ffmpeg.build_transcode_cmd('l.txt', 'o.mp4', 0, 10, 720)
    assert '-hwaccel' in cmd and cmd[cmd.index('-hwaccel') + 1] == 'cuda'
    # watermark + timelapse paths too
    assert '-hwaccel' in ffmpeg.build_timelapse_cmd('l.txt', 'o.mp4', 4)
    assert '-hwaccel' in ffmpeg.build_watermark_transcode_cmd('l.txt', 'o.mp4', 0, 10, 720, 'X')
