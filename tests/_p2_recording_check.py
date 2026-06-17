"""Manual P2 e2e: synthetic ffmpeg → go2rtc → recorder segments → playback → export.

Assumes a yaml `exec:` go2rtc stream `cam_synthetic_main` exists and disk dirs are
bind-mounted. Registers a disk, points a camera at the synthetic source, turns on
continuous recording, then validates segments/timeline/playback/export.
"""
import subprocess
import sys
import time

import requests

BACKEND = 'http://localhost:10000/api/v1'
SYNTH = 'cam_synthetic_main'
ok = fail = 0


def check(label, cond):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('  ✓ ' if cond else '  ✗ FAIL: ') + label)


def mysql(sql):
    subprocess.run(['docker', 'exec', 'axp-axp-mysql-1', 'mysql', '-uroot', '-paxp_root_pass', 'axp', '-e', sql],
                   capture_output=True)


print('— login')
token = requests.post(f'{BACKEND}/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'}).json()['data']['access_token']
H = {'Authorization': f'Bearer {token}'}

print('— register record disk (/mnt/axp/disk1)')
r = requests.post(f'{BACKEND}/storage/disks', headers=H,
                  json={'name': 'Disk1', 'mount_path': '/mnt/axp/disk1', 'role': 'record', 'reserved_free_bytes': 0})
check('disk register', r.status_code == 200 or 'already' in r.text)

print('— create camera + point main stream at synthetic source')
cam = requests.post(f'{BACKEND}/cameras', headers=H, json={
    'name': 'RecCam', 'host': '192.0.2.20', 'vendor': 'onvif', 'driver': 'onvif',
    'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
    'streams': [{'role': 'main', 'codec': 'h264', 'rtsp_path': '/main'}]}).json()['data']
uuid = cam['uuid']
# free the shared synthetic go2rtc_name from prior runs (UNIQUE) then repoint this camera
mysql(f"DELETE FROM streams WHERE go2rtc_name='{SYNTH}'; "
      f"UPDATE streams SET go2rtc_name='{SYNTH}' WHERE go2rtc_name='cam_{uuid}_main';")

print('— enable continuous recording')
r = requests.put(f'{BACKEND}/recording/cameras/{uuid}/mode', headers=H, json={'mode': 'continuous'})
check('record mode set', r.status_code == 200)

print('— wait for recorder to produce + index segments (up to 60s)...')
segments = []
for attempt in range(20):
    time.sleep(4)
    now_ms = int(time.time() * 1000)
    seg = requests.get(f'{BACKEND}/playback/cameras/{uuid}/segments', headers=H,
                       params={'from': now_ms - 600000, 'to': now_ms + 60000})
    segments = seg.json().get('data', {}).get('segments', []) if seg.status_code == 200 else []
    if len(segments) >= 2:
        break
    health = requests.get(f'{BACKEND}/recording/cameras/{uuid}/status', headers=H).json().get('data', {})
    print('    waiting… segments=%d recorder=%s' % (len(segments), health.get('health', {}).get('state')))
check('segments recorded + indexed (>=2)', len(segments) >= 2)

if segments:
    print('— timeline shows recording ranges')
    win_from = segments[0]['start_ts'] - 1000
    win_to = segments[-1]['end_ts'] + 1000
    tl = requests.get(f'{BACKEND}/playback/cameras/{uuid}/timeline', headers=H,
                      params={'from': win_from, 'to': win_to}).json()['data']
    check('timeline has ranges', len(tl['ranges']) >= 1)

    print('— playback: segment data serves video bytes (range)')
    sid = segments[0]['id']
    pb = requests.get(f'{BACKEND}/playback/segments/{sid}/data', params={'access_token': token},
                      headers={'Range': 'bytes=0-4095'}, stream=True, timeout=10)
    chunk = next(pb.iter_content(4096), b'') if pb.status_code in (200, 206) else b''
    check('segment data streams (206/200 + bytes)', pb.status_code in (200, 206) and len(chunk) > 100)

    print('— playback frame (on-demand JPEG)')
    fr = requests.get(f'{BACKEND}/playback/cameras/{uuid}/frame', headers=H,
                      params={'ts': segments[0]['start_ts'] + 2000})
    check('frame JPEG', fr.status_code == 200 and fr.headers.get('Content-Type', '').startswith('image'))

    print('— export clip (copy) → process → download')
    ex = requests.post(f'{BACKEND}/export/jobs', headers=H, json={
        'camera_uuid': uuid, 'start_ts': segments[0]['start_ts'], 'end_ts': segments[-1]['end_ts'], 'mode': 'copy'})
    job_id = ex.json().get('data', {}).get('job_id')
    check('export queued', ex.status_code == 200 and job_id)
    token_dl = None
    for _ in range(20):
        time.sleep(3)
        st = requests.get(f'{BACKEND}/export/jobs/{job_id}', headers=H).json()['data']
        if st['status'] == 'done':
            token_dl = st.get('download_token')
            break
        if st['status'] == 'failed':
            print('    export failed:', st.get('error_message'))
            break
    check('export completed', token_dl is not None)
    if token_dl:
        dl = requests.get(f'{BACKEND}/export/download/{token_dl}', params={'access_token': token}, stream=True)
        clip = next(dl.iter_content(8192), b'') if dl.status_code == 200 else b''
        check('clip downloads bytes', dl.status_code == 200 and len(clip) > 100)

print('— cleanup')
requests.put(f'{BACKEND}/recording/cameras/{uuid}/mode', headers=H, json={'mode': 'off'})
time.sleep(2)
requests.delete(f'{BACKEND}/cameras/{uuid}', headers=H)

print('\nRESULT: %d passed, %d failed' % (ok, fail))
sys.exit(1 if fail else 0)
