"""P6 Wave 2 — L2 privacy masks + R3 export watermark."""
from server.model import to_epoch_ms, utcnow
from tests.conftest import create_user, login

CAMERA = {'name': 'Mask', 'host': '192.0.2.110', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}
POLY = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.4], [0.1, 0.4]]


def _camera(client, h):
    return client.post('/api/v1/cameras', headers=h, json=CAMERA).json['data']


def test_privacy_mask_crud(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    cr = client.post(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h,
                     json={'name': '창문', 'polygon': POLY})
    assert cr.status_code == 200, cr.json
    mid = cr.json['data']['id']
    assert cr.json['data']['mode'] == 'server_render' and cr.json['data']['enabled'] is True

    lst = client.get(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h)
    assert lst.status_code == 200 and len(lst.json['data']['items']) == 1

    up = client.put(f'/api/v1/privacy-masks/{mid}', headers=h, json={'enabled': False, 'name': '이웃집'})
    assert up.status_code == 200 and up.json['data']['enabled'] is False and up.json['data']['name'] == '이웃집'

    assert client.delete(f'/api/v1/privacy-masks/{mid}', headers=h).status_code == 200
    assert len(client.get(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h).json['data']['items']) == 0


def test_privacy_mask_validation(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h,
                       json={'name': 'x', 'polygon': [[0.1, 0.1], [0.2, 0.2]]}).status_code == 400  # <3 pts
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h,
                       json={'polygon': POLY}).status_code == 400                                    # no name


def test_privacy_mask_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/privacy_masks', headers=h, json={'enabled': False})
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=h,
                       json={'name': 'x', 'polygon': POLY}).status_code == 403


def test_privacy_mask_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    create_user(client, h, 'mask_u', {'masks': ['read', 'update']})   # perm, no camera scope
    vh = login(client, 'mask_u', 'viewer1234!')
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/privacy-masks", headers=vh,
                       json={'name': 'x', 'polygon': POLY}).status_code == 403


# ── R3 export watermark ───────────────────────────────────────────────────────
def _patch_export(monkeypatch):
    from server.task.list import transcode
    monkeypatch.setattr(transcode.run_export_job, 'delay', lambda *a, **k: type('R', (), {'id': 'x'})())


def test_export_watermark_forces_transcode(client, mock_go2rtc, monkeypatch):
    _patch_export(monkeypatch)
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/export/jobs', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': now - 120_000, 'end_ts': now,
        'mode': 'copy', 'watermark': True, 'watermark_text': 'Evidence 2026'})
    assert r.status_code == 200, r.json
    job = client.get(f"/api/v1/export/jobs/{r.json['data']['job_id']}", headers=h).json['data']
    assert job['watermark'] is True and job['mode'] == 'transcode'   # watermark ⇒ re-encode


def test_export_watermark_flag_gate(client, mock_go2rtc, monkeypatch):
    _patch_export(monkeypatch)
    h = login(client)
    cam = _camera(client, h)
    client.put('/api/v1/feature-flags/export_watermark', headers=h, json={'enabled': False})
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/export/jobs', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': now - 1000, 'end_ts': now, 'watermark': True})
    assert r.status_code == 400


def test_watermark_text_sanitized():
    from server.service import ffmpeg
    out = ffmpeg.safe_watermark_text("증거'2026:\\%;rm")
    assert "'" not in out and '\\' not in out and '%' not in out and ';' not in out
    assert '증거' in out and '2026' in out and ':' in out
    cmd = ffmpeg.build_watermark_transcode_cmd('list.txt', 'out.mp4', 0.0, 5.0, 720, "x'y")
    vf = cmd[cmd.index('-vf') + 1]
    assert 'drawtext=' in vf and "x'y" not in vf            # injection chars stripped


def test_export_password_protected(client, mock_go2rtc, monkeypatch):
    _patch_export(monkeypatch)
    h = login(client)
    cam = _camera(client, h)
    now = to_epoch_ms(utcnow())
    r = client.post('/api/v1/export/jobs', headers=h, json={
        'camera_uuid': cam['uuid'], 'start_ts': now - 120_000, 'end_ts': now,
        'mode': 'copy', 'password': 'secret123'})
    assert r.status_code == 200, r.json
    job = client.get(f"/api/v1/export/jobs/{r.json['data']['job_id']}", headers=h).json['data']
    assert job['password_protected'] is True


def test_zip_with_password_roundtrip(tmp_path):
    import pyzipper
    from server.task.list.transcode import _zip_with_password
    src = tmp_path / 'clip.mp4'
    src.write_bytes(b'video-bytes-12345')
    zp = tmp_path / 'clip.zip'
    _zip_with_password(str(src), str(zp), 'pw123')
    with pyzipper.AESZipFile(str(zp)) as zf:
        zf.setpassword(b'pw123')
        assert zf.read('clip.mp4') == b'video-bytes-12345'
