"""P6 A4 — audio classification (glass break / scream / alarm …).

The real model (PANNs) lives in the detector image; the dependency-free energy stub runs
here, so `active_backend()=='stub'` in tests. Covered: classifier dispatch, PCM decode +
window→report building (worker), node ingest → audio_detections + threshold→audio_class
events, and the read/config API.
"""
import math
import struct

from server.model import db
from server.model.ai_node import KIND_REMOTE, STATUS_ONLINE, AiNode
from server.model.audio_detection import AudioDetection
from server.model.camera import Camera
from server.model.detection_assignment import DetectionAssignment
from tests.conftest import login


def _camera(name='audcam', ai=None) -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    if ai:
        c.ai_features = ai
    db.session.add(c)
    db.session.commit()
    return c


def _node(name='an1') -> AiNode:
    n = AiNode.create(name=name, kind=KIND_REMOTE)
    n.update(status=STATUS_ONLINE)
    return n


def _tone(freq, n=16000, sr=16000, amp=0.6):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


# ── classifier (stub) ────────────────────────────────────────────────────────
def test_classifier_backend_is_stub():
    from server.service import audio_classify
    assert audio_classify.active_backend() == 'stub'        # no panns/torch locally


def test_classifier_silence_is_ambient():
    from server.service import audio_classify
    out = audio_classify.classify([0.0] * 16000, 16000)
    assert out[0]['label'] == 'ambient' and out[0]['score'] == 0


def test_classifier_loud_tone_scores_high():
    from server.service import audio_classify
    out = audio_classify.classify(_tone(440, amp=0.7), 16000)
    assert out[0]['score'] >= 60                            # loud → high score
    assert out[0]['label'] != 'ambient'


def test_classifier_empty_input():
    from server.service import audio_classify
    assert audio_classify.classify([], 16000)[0]['label'] == 'ambient'


# ── worker: PCM decode + window build ────────────────────────────────────────
def test_pcm_to_floats_roundtrip():
    from worker.detector.audio import pcm_to_floats
    raw = struct.pack('<4h', 0, 32767, -32768, 16384)
    out = pcm_to_floats(raw)
    assert out[0] == 0.0
    assert abs(out[1] - 0.999969) < 1e-4
    assert out[2] == -1.0
    assert len(pcm_to_floats(b'\x01')) == 0                 # odd trailing byte ignored


def test_classify_window_drops_ambient_and_builds_rows():
    from worker.detector import audio
    assert audio.classify_window([0.0] * 16000, 7, 1234) == []   # ambient dropped
    rows = audio.classify_window(_tone(440, amp=0.7), 7, 1234)
    assert rows and rows[0]['camera_id'] == 7 and rows[0]['ts'] == 1234
    assert 0 <= rows[0]['score'] <= 100


# ── ingest: persist + threshold→event ────────────────────────────────────────
def test_ingest_requires_assignment(app_db):
    from server.service import audio_ingest
    node, cam = _node(), _camera()
    res = audio_ingest.ingest_batch(node, [{'camera_id': cam.id, 'label': 'alarm', 'score': 90}])
    assert res['accepted'] == 0 and res['rejected'][0]['reason'] == 'not_assigned'


def test_ingest_persists_and_raises_event(app_db):
    from server.model.event import Event, TYPE_AUDIO_CLASS
    from server.service import audio_ingest
    node, cam = _node(), _camera(ai={'audio': True})   # per-camera AI enable
    DetectionAssignment.assign(cam.id, node.id)
    res = audio_ingest.ingest_batch(node, [
        {'camera_id': cam.id, 'label': 'glass_break', 'score': 95},   # ≥ threshold(60) → event
        {'camera_id': cam.id, 'label': 'speech', 'score': 20},        # below → stored, no event
    ])
    assert res['accepted'] == 2
    assert len(AudioDetection.recent_for_camera(cam.id)) == 2
    evs = db.session.query(Event).filter(Event.camera_id == cam.id, Event.type == TYPE_AUDIO_CLASS).all()
    assert len(evs) == 1 and evs[0].subtype == 'glass_break'


def test_ingest_feature_off_no_events(app_db):
    """Camera without ai_features.audio → windows stored but no events raised."""
    from server.model.event import Event, TYPE_AUDIO_CLASS
    from server.service import audio_ingest
    node, cam = _node(), _camera()                                   # audio off (default)
    DetectionAssignment.assign(cam.id, node.id)
    res = audio_ingest.ingest_batch(node, [{'camera_id': cam.id, 'label': 'alarm', 'score': 99}])
    assert res['accepted'] == 1                                       # stored
    assert db.session.query(Event).filter(Event.type == TYPE_AUDIO_CLASS).count() == 0  # but no event


# ── API: read + config ───────────────────────────────────────────────────────
def test_audio_labels_endpoint(client, mock_go2rtc):
    h = login(client)
    r = client.get('/api/v1/audio/labels', headers=h)
    assert r.status_code == 200, r.json
    assert 'glass_break' in r.json['data']['labels'] and r.json['data']['backend'] == 'stub'


def test_audio_detections_list_scoped(client, mock_go2rtc):
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'A', 'host': '192.0.2.200', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']
    from server.model import utcnow
    AudioDetection.bulk_create([{'camera_id': int(cam['id']), 'ts': utcnow(), 'label': 'alarm', 'score': 80}])
    r = client.get(f"/api/v1/cameras/{cam['uuid']}/audio-detections", headers=h)
    assert r.status_code == 200, r.json
    assert len(r.json['data']['items']) == 1 and r.json['data']['items'][0]['label'] == 'alarm'


def test_ai_settings_audio_config(client, mock_go2rtc):
    h = login(client)
    up = client.put('/api/v1/ai/settings', headers=h, json={'audio_enabled': True, 'audio_threshold': 75})
    assert up.status_code == 200, up.json
    assert up.json['data']['audio_enabled'] is True and up.json['data']['audio_threshold'] == 75
