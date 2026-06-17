"""Manual P1 live e2e: synthetic ffmpeg pattern -> go2rtc -> backend proxy.

Assumes a yaml `exec:` stream named `cam_synthetic_sub` already exists in go2rtc
(the caller swaps it in). Validates camera CRUD + encrypted creds + live fMP4 proxy
auth/media + snapshot, repointing a real DB camera's stream at the synthetic source.
"""
import subprocess
import sys
import time

import requests

BACKEND = 'http://localhost:10000/api/v1'
GO2RTC = 'http://localhost:1984'
SYNTH = 'cam_synthetic_sub'
ok = fail = 0


def check(label, cond):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('  ✓ ' if cond else '  ✗ FAIL: ') + label)


def read_media(url, params=None, headers=None, tries=8):
    for _ in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, stream=True, timeout=8)
            if r.status_code == 200:
                chunk = next(r.iter_content(4096), b'')
                r.close()
                if chunk and (b'ftyp' in chunk or b'moof' in chunk or len(chunk) > 200):
                    return chunk
            else:
                r.close()
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    return None


print('— go2rtc serves the synthetic exec stream (ffmpeg test pattern)')
check('go2rtc /api/stream.mp4 media', read_media(f'{GO2RTC}/api/stream.mp4', params={'src': SYNTH}) is not None)

print('— login + create camera (encrypted creds)')
token = requests.post(f'{BACKEND}/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'}).json()['data']['access_token']
H = {'Authorization': f'Bearer {token}'}
cam = requests.post(f'{BACKEND}/cameras', headers=H, json={
    'name': 'Synthetic', 'host': '192.0.2.10', 'vendor': 'onvif', 'driver': 'onvif',
    'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
    'streams': [{'role': 'sub', 'codec': 'h264', 'rtsp_path': '/sub'}]}).json()['data']
uuid = cam['uuid']
check('credentials not leaked in response', 'secret' not in str(cam))

print('— repoint the camera sub stream at the synthetic go2rtc source')
subprocess.run(['docker', 'exec', 'axp-axp-mysql-1', 'mysql', '-uroot', '-paxp_root_pass', 'axp',
                '-e', f"UPDATE streams SET go2rtc_name='{SYNTH}' WHERE go2rtc_name='cam_{uuid}_sub';"],
               capture_output=True)

print('— live fMP4 proxy: no token -> 401')
r = requests.get(f'{BACKEND}/live/mp4/{SYNTH}', stream=True, timeout=8)
check('401 without token', r.status_code == 401)
r.close()

print('— live fMP4 proxy: with token -> real media bytes')
check('backend proxy streams media', read_media(f'{BACKEND}/live/mp4/{SYNTH}', params={'access_token': token}) is not None)

print('— snapshot (JPEG via go2rtc frame)')
got = False
for _ in range(6):
    s = requests.get(f'{BACKEND}/cameras/{uuid}/snapshot', headers=H, timeout=8)
    if s.status_code == 200 and s.headers.get('Content-Type', '').startswith('image') and len(s.content) > 500:
        got = True
        break
    time.sleep(2)
check('snapshot returns JPEG', got)

requests.delete(f'{BACKEND}/cameras/{uuid}', headers=H)
print('\nRESULT: %d passed, %d failed' % (ok, fail))
sys.exit(1 if fail else 0)
