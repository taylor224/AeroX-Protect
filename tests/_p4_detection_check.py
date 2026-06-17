"""Manual P4 e2e: a mock AI node drives the full distributed flow against the live stack —
pre-register → join → heartbeat → assignments(etag/304) → ingest detections → smart search
→ overlay → object trigger → P3 object event + recording → timeline. Reuses the P3 synthetic
recorder so detections link to real segments (clip playback). Run:
    .venv/bin/python tests/_p4_detection_check.py
"""
import subprocess
import sys
import time

import requests

BACKEND = 'http://localhost:10000/api/v1'
SYNTH = 'cam_synthetic_main'
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

print('— camera + synthetic recording (for segment linking)')
requests.post(f'{BACKEND}/storage/disks', headers=H,
              json={'name': 'Disk1', 'mount_path': '/mnt/axp/disk1', 'role': 'record', 'reserved_free_bytes': 0})
cam = requests.post(f'{BACKEND}/cameras', headers=H, json={
    'name': 'AiCam', 'host': '192.0.2.50', 'vendor': 'onvif', 'driver': 'onvif',
    'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
    'streams': [{'role': 'main', 'codec': 'h264', 'rtsp_path': '/main'}]}).json()['data']
uuid, cam_id = cam['uuid'], int(cam['id'])
mysql(f"DELETE FROM streams WHERE go2rtc_name='{SYNTH}'; "
      f"UPDATE streams SET go2rtc_name='{SYNTH}' WHERE go2rtc_name='cam_{uuid}_main';")
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
    print('    waiting for segments… %d' % len(segments))
check('synthetic segments recorded (>=2)', len(segments) >= 2)
seg_ts = segments[0]['start_ts'] + 2000 if segments else int(time.time() * 1000)

# ── distributed node: pre-register → join ───────────────────────────────────────
print('— pre-register node + join')
cr = requests.post(f'{BACKEND}/ai-nodes', headers=H, json={'name': 'mock-node'})
join_token = cr.json()['data']['join_token']
node = cr.json()['data']['node']
check('join token issued', bool(join_token))
jr = requests.post(f'{BACKEND}/ai/nodes/join', headers={'Authorization': f'Bearer {join_token}'},
                   json={'name': 'mock-node', 'gpu': False, 'capacity': 4, 'capabilities': {'models': ['yolov8n']}})
node_token = jr.json().get('data', {}).get('node_token')
check('node joined (token issued)', bool(node_token))
NH = {'Authorization': f'Bearer {node_token}'}

print('— heartbeat + assignments (camera assigned via rebalance)')
hb = requests.post(f'{BACKEND}/ai/nodes/heartbeat', headers=NH, json={'status': 'online'})
check('heartbeat ok', hb.status_code == 200 and 'assignments_etag' in hb.json().get('data', {}))
asg = requests.get(f'{BACKEND}/ai/nodes/assignments', headers=NH)
items = asg.json().get('data', {}).get('items', []) if asg.status_code == 200 else []
spec = next((s for s in items if int(s['camera_id']) == cam_id), None)
check('camera assigned to node (CameraJobSpec)', spec is not None)
check('job spec has rtsp_url + labels', bool(spec and spec.get('rtsp_url') and spec.get('labels')) if spec else False)
etag = asg.json().get('data', {}).get('etag')
epoch = spec['epoch'] if spec else 1
asg304 = requests.get(f'{BACKEND}/ai/nodes/assignments', headers={**NH, 'If-None-Match': etag or ''})
check('assignments 304 on matching etag', asg304.status_code == 304)

print('— ingest detection batch (person/car, ts inside a segment)')
batch = [
    {'camera_id': cam_id, 'ts': seg_ts, 'epoch': epoch, 'class_id': 0, 'confidence': 0.91,
     'bbox': [0.40, 0.45, 0.52, 0.85], 'frame_w': 1280, 'frame_h': 720, 'bytetrack_id': 1},
    {'camera_id': cam_id, 'ts': seg_ts + 500, 'epoch': epoch, 'class_id': 0, 'confidence': 0.88,
     'bbox': [0.41, 0.46, 0.53, 0.86], 'frame_w': 1280, 'frame_h': 720, 'bytetrack_id': 1},
    {'camera_id': cam_id, 'ts': seg_ts + 1000, 'epoch': epoch, 'class_id': 2, 'confidence': 0.77,
     'bbox': [0.10, 0.50, 0.30, 0.80], 'frame_w': 1280, 'frame_h': 720, 'bytetrack_id': 2},
]
ing = requests.post(f'{BACKEND}/ai/ingest/detections', headers=NH, json={'batch': batch, 'epoch_map': {str(cam_id): epoch}})
check('detections accepted', ing.status_code == 200 and ing.json()['data']['accepted'] == 3, ing.text[:200])

print('— stale epoch rejected')
bad = requests.post(f'{BACKEND}/ai/ingest/detections', headers=NH, json={'batch': [
    {'camera_id': cam_id, 'ts': seg_ts, 'epoch': 999, 'class_id': 0, 'confidence': 0.9, 'bbox': [0, 0, 0.1, 0.1]}]})
check('stale-epoch report rejected', bad.json()['data']['accepted'] == 0 and bad.json()['data']['rejected'])

# ── smart search / overlay ───────────────────────────────────────────────────────
print('— smart search (person, clip group)')
sr = requests.get(f'{BACKEND}/detections/search', headers=H,
                  params={'camera_id': cam_id, 'label': 'person', 'group': 'clip'})
sd = sr.json().get('data', {}) if sr.status_code == 200 else {}
check('search returns a person clip', sd.get('count', 0) >= 1 and sd['items'][0]['labels'] == ['person'])
rep_id = sd['items'][0]['rep_detection_id'] if sd.get('items') else None

if rep_id:
    det = requests.get(f'{BACKEND}/detections/{rep_id}', headers=H).json()['data']
    check('detection linked to a segment', det.get('segment_id') is not None, str(det.get('segment_id')))

print('— overlay tracks for the clip window')
ov = requests.get(f'{BACKEND}/detections/overlay', headers=H,
                  params={'camera_id': uuid, 'start': seg_ts - 5000, 'end': seg_ts + 5000})
ovd = ov.json().get('data', {}) if ov.status_code == 200 else {}
check('overlay has tracks with bbox points', len(ovd.get('tracks', [])) >= 1 and ovd['tracks'][0]['points'])

print('— timeline markers + coverage')
tl = requests.get(f'{BACKEND}/detections/timeline', headers=H,
                  params={'camera_id': uuid, 'start': seg_ts - 10000, 'end': seg_ts + 10000})
tld = tl.json().get('data', {}) if tl.status_code == 200 else {}
check('detection timeline has markers', len(tld.get('markers', [])) >= 1)

# ── object trigger → P3 object event → recording ─────────────────────────────────
print('— object trigger → P3 object event → recording')
requests.post(f'{BACKEND}/event-policies', headers=H, json={
    'camera_uuid': uuid, 'event_type': 'object', 'action': 'record', 'pre_buffer_s': 5, 'post_buffer_s': 10})
requests.post(f'{BACKEND}/object-triggers', headers=H, json={
    'camera_uuid': uuid, 'name': 'person', 'labels': ['person'], 'min_confidence': 50})
requests.post(f'{BACKEND}/ai/ingest/detections', headers=NH, json={'batch': [
    {'camera_id': cam_id, 'ts': int(time.time() * 1000), 'epoch': epoch, 'class_id': 0, 'confidence': 0.95,
     'bbox': [0.4, 0.4, 0.6, 0.85], 'bytetrack_id': 77}]})
time.sleep(1)
ev = requests.get(f'{BACKEND}/events', headers=H, params={'type': 'object'})
evd = ev.json().get('data', {}) if ev.status_code == 200 else {}
obj_ev = evd.get('items', [{}])[0] if evd.get('count') else {}
check('object event created from trigger', evd.get('count', 0) >= 1 and obj_ev.get('type') == 'object')
check('object event has a recording (P3 policy)', bool(obj_ev.get('recording_id')))

# ── distributed: 2nd node + rebalance ────────────────────────────────────────────
print('— add a 2nd node + rebalance')
rb = requests.post(f'{BACKEND}/ai/assignments/rebalance', headers=H)
check('rebalance ok', rb.status_code == 200 and 'assigned' in rb.json().get('data', {}))
asgs = requests.get(f'{BACKEND}/ai/assignments', headers=H).json()['data']['items']
check('assignment recorded for camera', any(int(a['camera_id']) == cam_id for a in asgs))

print('— cleanup')
requests.put(f'{BACKEND}/recording/cameras/{uuid}/mode', headers=H, json={'mode': 'off'})
requests.delete(f"/ai-nodes/{node['id']}" and f"{BACKEND}/ai-nodes/{node['id']}", headers=H)
time.sleep(2)
requests.delete(f'{BACKEND}/cameras/{uuid}', headers=H)

print('\nRESULT: %d passed, %d failed' % (ok, fail))
sys.exit(1 if fail else 0)
