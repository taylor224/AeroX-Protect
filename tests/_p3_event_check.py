"""Manual P3 e2e: synthetic recorder segments → simulate event → event clip (cache
buffer) → event list/timeline/overlay/playback → schedule resolver → timelapse.

Builds on the P2 synthetic pattern: assumes a yaml `exec:` go2rtc stream
`cam_synthetic_main` exists and disks are bind-mounted. Run against the live stack:
    .venv/bin/python tests/_p3_event_check.py
"""
import subprocess
import sys
import time

import requests

BACKEND = 'http://localhost:10000/api/v1'
SYNTH = 'cam_synthetic_main'
KST_OFFSET = 9 * 3600
ok = fail = 0


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('  ✓ ' if cond else '  ✗ FAIL: ') + label + (('  — ' + extra) if extra and not cond else ''))


def mysql(sql):
    subprocess.run(['docker', 'exec', 'axp-axp-mysql-1', 'mysql', '-uroot', '-paxp_root_pass', 'axp', '-e', sql],
                   capture_output=True)


print('— login')
token = requests.post(f'{BACKEND}/auth/login',
                      json={'login_id': 'admin', 'password': 'admin1234!'}).json()['data']['access_token']
H = {'Authorization': f'Bearer {token}'}

print('— register record disk')
requests.post(f'{BACKEND}/storage/disks', headers=H,
              json={'name': 'Disk1', 'mount_path': '/mnt/axp/disk1', 'role': 'record', 'reserved_free_bytes': 0})

print('— create camera + repoint to synthetic source')
cam = requests.post(f'{BACKEND}/cameras', headers=H, json={
    'name': 'EvtCam', 'host': '192.0.2.30', 'vendor': 'onvif', 'driver': 'onvif',
    'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
    'streams': [{'role': 'main', 'codec': 'h264', 'rtsp_path': '/main'}]}).json()['data']
uuid = cam['uuid']
check('camera DTO exposes numeric id (frontend join key)', bool(cam.get('id')), repr(cam.get('id')))
mysql(f"DELETE FROM streams WHERE go2rtc_name='{SYNTH}'; "
      f"UPDATE streams SET go2rtc_name='{SYNTH}' WHERE go2rtc_name='cam_{uuid}_main';")

print('— enable continuous recording, wait for segments (up to 80s)')
requests.put(f'{BACKEND}/recording/cameras/{uuid}/mode', headers=H, json={'mode': 'continuous'})
segments = []
for _ in range(20):
    time.sleep(4)
    now_ms = int(time.time() * 1000)
    seg = requests.get(f'{BACKEND}/playback/cameras/{uuid}/segments', headers=H,
                       params={'from': now_ms - 600000, 'to': now_ms + 60000})
    segments = seg.json().get('data', {}).get('segments', []) if seg.status_code == 200 else []
    if len(segments) >= 2:
        break
    st = requests.get(f'{BACKEND}/recording/cameras/{uuid}/status', headers=H).json().get('data', {})
    print('    waiting… segments=%d recorder=%s' % (len(segments), st.get('health', {}).get('state')))
check('segments recorded + indexed (>=2)', len(segments) >= 2)

# ── event pipeline ─────────────────────────────────────────────────────────────
print('— simulate motion event (with region) → event clip via cache buffer')
region = {'shapes': [{'kind': 'poly', 'pts': [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]}], 'w': 1, 'h': 1}
sim = requests.post(f'{BACKEND}/events/simulate', headers=H,
                    json={'camera_uuid': uuid, 'type': 'motion', 'score': 90, 'region': region})
ev = sim.json().get('data', {}) if sim.status_code == 200 else {}
event_id = ev.get('id')
check('event created', sim.status_code == 200 and bool(event_id), sim.text[:200])
check('policy action = record (seeded global motion policy)', ev.get('policy_action') == 'record', str(ev.get('policy_action')))
check('event clip materialized (recording_id set)', bool(ev.get('recording_id')))

if ev.get('recording_id'):
    rec = requests.get(f'{BACKEND}/recording/cameras/{uuid}/status', headers=H)  # warm
    # verify the recording row is an event clip via DB (reason/class)
    out = subprocess.run(
        ['docker', 'exec', 'axp-axp-mysql-1', 'mysql', '-uroot', '-paxp_root_pass', 'axp', '-N', '-e',
         f"SELECT reason, retention_class FROM recordings WHERE id={ev['recording_id']};"],
        capture_output=True, text=True).stdout.strip()
    check('recording reason=event, class=event', out.startswith('event\tevent'), out)

print('— event list + detail')
lst = requests.get(f'{BACKEND}/events', headers=H, params={'camera_id': cam.get('id')})
items = lst.json().get('data', {}).get('items', []) if lst.status_code == 200 else []
check('event appears in filtered list', any(e['id'] == event_id for e in items))
detail = requests.get(f'{BACKEND}/events/{event_id}', headers=H)
check('event detail fetch', detail.status_code == 200 and detail.json()['data']['type'] == 'motion')

print('— event timeline markers + coverage')
win_from = segments[0]['start_ts'] - 5000
win_to = segments[-1]['end_ts'] + 60000
tl = requests.get(f'{BACKEND}/events/timeline', headers=H,
                  params={'camera_id': uuid, 'start': win_from, 'end': win_to})
tldata = tl.json().get('data', {}) if tl.status_code == 200 else {}
check('timeline has event marker', any(m['event_id'] == event_id for m in tldata.get('markers', [])))
check('timeline has recording coverage', len(tldata.get('coverage', [])) >= 1)

print('— event overlay (0–1 region scaled)')
ov = requests.get(f'{BACKEND}/events/{event_id}/overlay', headers=H)
ovd = ov.json().get('data', {}) if ov.status_code == 200 else {}
shapes = ovd.get('shapes', [])
check('overlay returns region polygon', len(shapes) == 1 and len(shapes[0].get('pts', [])) == 4)

print('— event clip plays back (segment in clip window streams bytes)')
sid = segments[0]['id']
pb = requests.get(f'{BACKEND}/playback/segments/{sid}/data', params={'access_token': token},
                  headers={'Range': 'bytes=0-4095'}, stream=True, timeout=10)
chunk = next(pb.iter_content(4096), b'') if pb.status_code in (200, 206) else b''
check('event clip segment streams', pb.status_code in (200, 206) and len(chunk) > 100)

# ── schedule resolver ──────────────────────────────────────────────────────────
print('— schedule: paint current slot OFF → resolver/combine reflect it')
kst = time.gmtime(time.time() + KST_OFFSET)
dow = (kst.tm_wday)  # Mon=0..Sun=6 (KST)
requests.put(f'{BACKEND}/cameras/{uuid}/schedule', headers=H, json={
    'rules': [{'day_of_week': dow, 'start_min': 0, 'end_min': 1440, 'mode': 'off', 'priority': 10}]})
sch = requests.get(f'{BACKEND}/cameras/{uuid}/schedule', headers=H).json()['data']['rules']
check('schedule rule saved', any(r['mode'] == 'off' for r in sch))
rp = requests.post(f'{BACKEND}/event-policies/resolve', headers=H, json={'camera_uuid': uuid, 'type': 'motion'})
rpd = rp.json().get('data', {}) if rp.status_code == 200 else {}
check('resolver schedule_mode = off', rpd.get('schedule_mode') == 'off', str(rpd))
check('combine(record, off) = discard', rpd.get('action') == 'discard', str(rpd))
# restore to default (continuous) so timelapse/recording isn't gated
requests.put(f'{BACKEND}/cameras/{uuid}/schedule', headers=H, json={'rules': []})

# ── timelapse ──────────────────────────────────────────────────────────────────
print('— timelapse over recorded window → progress → download')
tlj = requests.post(f'{BACKEND}/timelapse', headers=H, json={
    'camera_uuid': uuid, 'range_start': segments[0]['start_ts'], 'range_end': segments[-1]['end_ts'],
    'speed_factor': 60})
job = tlj.json().get('data', {}) if tlj.status_code == 200 else {}
job_id = job.get('id')
check('timelapse queued', tlj.status_code == 200 and bool(job_id), tlj.text[:200])
final = {}
for _ in range(25):
    time.sleep(4)
    final = requests.get(f'{BACKEND}/timelapse/{job_id}', headers=H).json().get('data', {})
    if final.get('status') in ('done', 'failed'):
        break
    print('    timelapse… status=%s progress=%s' % (final.get('status'), final.get('progress')))
check('timelapse done', final.get('status') == 'done', 'status=%s err=%s' % (final.get('status'), final.get('error')))
if final.get('status') == 'done':
    dl = requests.get(f'{BACKEND}/timelapse/{job_id}/download', params={'access_token': token}, stream=True)
    clip = next(dl.iter_content(8192), b'') if dl.status_code == 200 else b''
    check('timelapse downloads mp4 bytes', dl.status_code == 200 and len(clip) > 100)

print('— cleanup')
requests.put(f'{BACKEND}/recording/cameras/{uuid}/mode', headers=H, json={'mode': 'off'})
time.sleep(2)
requests.delete(f'{BACKEND}/cameras/{uuid}', headers=H)

print('\nRESULT: %d passed, %d failed' % (ok, fail))
sys.exit(1 if fail else 0)
