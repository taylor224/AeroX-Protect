"""P7 A8 — face recognition (identities + observations + face events).

A real face embedder runs on the node; the server matches embeddings (brute-force cosine)
against a consented identity registry and raises `face` events on known hits. Tested:
matching, enrollment + consent gate, the ingest path, right-to-erasure, and the API.
Event raising is gated per-camera by `ai_features.face` (off by default); the identity
registry is global config.
"""
from server.model import db
from server.model.ai_node import KIND_REMOTE, STATUS_ONLINE, AiNode
from server.model.camera import Camera
from server.model.detection_assignment import DetectionAssignment
from server.model.event import TYPE_FACE, Event
from server.model.face_identity import FaceIdentity
from server.model.face_observation import FaceObservation
from tests.conftest import login

VEC_A = [1.0, 0.0, 0.0, 0.0]
VEC_A2 = [0.96, 0.10, 0.0, 0.0]      # close to A → cosine ≈ 0.99
VEC_B = [0.0, 1.0, 0.0, 0.0]         # orthogonal to A → cosine 0


def _camera(name='facecam', ai=None) -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    if ai:
        c.ai_features = ai
    db.session.add(c)
    db.session.commit()
    return c


def _node(name='fn1') -> AiNode:
    n = AiNode.create(name=name, kind=KIND_REMOTE)
    n.update(status=STATUS_ONLINE)
    return n


def _identity(name='Alice', vec=VEC_A, backend='facenet') -> FaceIdentity:
    i = FaceIdentity.create(name=name, consent=True)
    i.add_embedding(vec, backend, len(vec))
    return i


# ── matching ─────────────────────────────────────────────────────────────────
def test_face_match_known_and_unknown(app_db):
    from server.service import face_match
    _identity('Alice', VEC_A)
    ident, score = face_match.match(VEC_A2, 'facenet')
    assert ident is not None and ident.name == 'Alice' and score >= 90
    assert face_match.match(VEC_B, 'facenet') == (None, 0)         # orthogonal → no match
    assert face_match.match(VEC_A, 'other_backend') == (None, 0)   # backend mismatch


def test_type_registered():
    from server.service.event_normalizer import VALID_TYPES
    assert TYPE_FACE in VALID_TYPES


# ── erasure + consent ────────────────────────────────────────────────────────
def test_soft_delete_wipes_embeddings(app_db):
    i = _identity()
    assert i.embeddings and len(i.embeddings) == 1
    i.soft_delete()
    assert i.embeddings is None                                    # right to erasure
    assert FaceIdentity.get_by_id(i.id) is None


# ── worker report builder ────────────────────────────────────────────────────
def test_build_report_quality_floor():
    from worker.detector import face
    assert face.build_report(1, VEC_A, 'facenet', quality=80)['backend'] == 'facenet'
    assert face.build_report(1, VEC_A, 'facenet', quality=10) is None     # below floor
    assert face.build_report(1, [], 'facenet') is None                    # empty


# ── ingest ───────────────────────────────────────────────────────────────────
def test_ingest_requires_assignment(app_db):
    from server.service import face_ingest
    node, cam = _node(), _camera(ai={'face': True})
    res = face_ingest.ingest_batch(node, [{'camera_id': cam.id, 'embedding': VEC_A, 'backend': 'facenet'}])
    assert res['accepted'] == 0 and res['rejected'][0]['reason'] == 'not_assigned'


def test_ingest_matches_and_raises(app_db):
    from server.service import face_ingest
    node, cam = _node(), _camera(ai={'face': True})   # per-camera AI enable
    DetectionAssignment.assign(cam.id, node.id)
    _identity('Bob', VEC_A)
    res = face_ingest.ingest_batch(node, [
        {'camera_id': cam.id, 'embedding': VEC_A2, 'backend': 'facenet', 'quality': 90},  # → Bob
        {'camera_id': cam.id, 'embedding': VEC_B, 'backend': 'facenet', 'quality': 90},   # unknown
    ])
    assert res['accepted'] == 2 and res['matched'] == 1
    obs = FaceObservation.recent_for_camera(cam.id)
    known = [o for o in obs if o.identity_name == 'Bob']
    assert len(known) == 1 and known[0].score >= 90
    evs = db.session.query(Event).filter(Event.camera_id == cam.id, Event.type == TYPE_FACE).all()
    assert len(evs) == 1 and evs[0].subtype == 'known'


def test_ingest_feature_off_stores_no_match(app_db):
    """Camera without ai_features.face → observations stored, but no match/event."""
    from server.service import face_ingest
    node, cam = _node(), _camera()                    # face off (default)
    DetectionAssignment.assign(cam.id, node.id)
    _identity('Bob', VEC_A)
    res = face_ingest.ingest_batch(node, [{'camera_id': cam.id, 'embedding': VEC_A, 'backend': 'facenet'}])
    assert res['accepted'] == 1 and res['matched'] == 0
    assert db.session.query(Event).filter(Event.type == TYPE_FACE).count() == 0


# ── API ──────────────────────────────────────────────────────────────────────
def test_identity_crud_and_enroll_api(client, mock_go2rtc, monkeypatch):
    from server.service import feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    h = login(client)
    # create identity (no consent yet)
    cid = client.post('/api/v1/face/identities', headers=h, json={'name': 'Carol'}).json['data']['id']
    assert len(client.get('/api/v1/face/identities', headers=h).json['data']['items']) == 1
    # enroll without consent → 400
    r = client.post(f'/api/v1/face/identities/{cid}/enroll', headers=h,
                    json={'embedding': VEC_A, 'backend': 'facenet'})
    assert r.status_code == 400
    # grant consent, then enroll a raw embedding
    client.put(f'/api/v1/face/identities/{cid}', headers=h, json={'consent': True})
    r = client.post(f'/api/v1/face/identities/{cid}/enroll', headers=h,
                    json={'embedding': VEC_A, 'backend': 'facenet'})
    assert r.status_code == 200 and r.json['data']['embedding_count'] == 1
    assert 'embeddings' not in r.json['data']                       # raw vectors never exposed
    # delete (erasure)
    client.delete(f'/api/v1/face/identities/{cid}', headers=h)
    assert client.get('/api/v1/face/identities', headers=h).json['data']['items'] == []


def test_camera_faces_and_search_api(client, mock_go2rtc, monkeypatch):
    from server.service import feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'C', 'host': '192.0.2.220', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']
    assert client.get(f"/api/v1/cameras/{cam['uuid']}/faces", headers=h).json['data']['items'] == []
    assert client.get('/api/v1/faces/search?known_only=1', headers=h).status_code == 200
