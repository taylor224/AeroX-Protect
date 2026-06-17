"""Regression tests for the post-P10 audit fixes:
- ingest poison-pill (bad camera_id rejects the row, not the batch)
- door relock scheduling + onvif_relay 'skipped' no longer marks a door unlocked
- credential validity window can be cleared
- distinct security alerts get distinct event dedup keys (no cooldown collapse)
- custom role delete (with system-role + in-use guards)
"""
from datetime import timedelta

from server.model import db, utcnow
from server.model.access_credential import AccessCredential
from server.model.ai_node import KIND_REMOTE, STATUS_ONLINE, AiNode
from server.model.camera import Camera
from server.model.detection_assignment import DetectionAssignment
from server.model.door import STATE_LOCKED, Door
from tests.conftest import login


def _camera(name='c') -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    db.session.add(c)
    db.session.commit()
    return c


def _node() -> AiNode:
    n = AiNode.create(name='n', kind=KIND_REMOTE)
    n.update(status=STATUS_ONLINE)
    return n


# ── poison-pill: one bad camera_id must not drop the whole batch ─────────────
def test_detection_ingest_bad_camera_id_rejects_only_that_row(app_db):
    from server.service import detection_ingest
    node, cam = _node(), _camera()
    DetectionAssignment.assign(cam.id, node.id)
    res = detection_ingest.ingest_batch(node, [
        {'camera_id': 'not-a-number', 'class_id': 0, 'confidence': 0.9, 'bbox': [0.1, 0.2, 0.3, 0.4], 'epoch': 1},
        {'camera_id': cam.id, 'class_id': 0, 'confidence': 0.9, 'bbox': [0.1, 0.2, 0.3, 0.4], 'epoch': 1},
    ])
    assert res['accepted'] == 1                                # the good row survived
    assert any(r['reason'] == 'bad_camera_id' for r in res['rejected'])


def test_lpr_ingest_bad_camera_id_rejects_only_that_row(app_db, monkeypatch):
    from server.service import feature_flag, lpr_ingest
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    node, cam = _node(), _camera()
    DetectionAssignment.assign(cam.id, node.id)
    res = lpr_ingest.ingest_batch(node, [
        {'camera_id': ['bad'], 'plate_text': 'AAA111', 'confidence': 90},
        {'camera_id': cam.id, 'plate_text': 'BBB222', 'confidence': 90},
    ])
    assert res['accepted'] == 1
    assert any(r['reason'] == 'bad_camera_id' for r in res['rejected'])


# ── door relock + onvif_relay correctness ────────────────────────────────────
def _cred(card, group='default'):
    return AccessCredential.create({'card_number': card, 'holder_name': 'H', 'access_group': group})


def test_door_auto_relocks_at_read_time(app_db):
    """A momentary unlock reverts to 'locked' once its window elapses — no broker/task,
    computed at read time so the API never reports a door open forever."""
    from server.service import access_control
    door = Door.create({'name': 'D', 'controller_type': 'mock', 'access_group': 'default', 'unlock_seconds': 5})
    _cred('RK')
    access_control.process_swipe(door, 'RK')
    assert Door.get_by_id(door.id).to_dict()['lock_state'] == 'unlocked'   # within the pulse window
    d = Door.get_by_id(door.id)
    d.unlocked_at = utcnow() - timedelta(seconds=10)                       # window elapsed
    db.session.add(d)
    db.session.commit()
    assert Door.get_by_id(door.id).to_dict()['lock_state'] == STATE_LOCKED  # auto-relocked at read


def test_onvif_relay_swipe_does_not_mark_unlocked(app_db):
    from server.service import access_control
    door = Door.create({'name': 'O', 'controller_type': 'onvif_relay', 'access_group': 'default'})
    _cred('OV')
    res = access_control.process_swipe(door, 'OV')
    assert res['granted'] is True                              # decision is granted…
    assert Door.get_by_id(door.id).lock_state == STATE_LOCKED  # …but the relay never actuated → stays locked


# ── credential validity can be cleared ───────────────────────────────────────
def test_credential_validity_can_be_cleared(app_db):
    c = AccessCredential.create({'card_number': 'V1', 'holder_name': 'V',
                                 'valid_until': utcnow() + timedelta(days=1)})
    assert c.valid_until is not None
    c.modify({'valid_until': None})
    assert AccessCredential.get_by_id(c.id).valid_until is None


# ── distinct security alerts get distinct dedup keys ─────────────────────────
def test_event_dedup_extra_distinguishes_identities(app_db, mock_go2rtc):
    from server.service import event_pipeline
    from server.model.event import TYPE_LPR, Event
    cam = _camera()
    # two different plates, same camera/type/subtype → distinct events thanks to dedup_extra
    e1 = event_pipeline.ingest_object(cam.id, {'type': TYPE_LPR, 'state': 'pulse', 'subtype': 'deny',
                                               'source': 'lpr', 'dedup_extra': 'ABC123'})
    e2 = event_pipeline.ingest_object(cam.id, {'type': TYPE_LPR, 'state': 'pulse', 'subtype': 'deny',
                                               'source': 'lpr', 'dedup_extra': 'XYZ789'})
    assert e1 is not None and e2 is not None and e1.id != e2.id
    assert db.session.query(Event).filter(Event.camera_id == cam.id, Event.type == TYPE_LPR).count() == 2


# ── recording is schedule-driven for all enabled cameras (no per-camera stop) ────
def test_recorder_records_all_enabled_cameras_per_schedule(app_db):
    from worker.recorder.supervisor import RecorderSupervisor
    cam_a, cam_b = _camera('a'), _camera('b')
    cam_off = _camera('off')
    cam_off.is_enabled = False
    db.session.add(cam_off)
    db.session.commit()
    # No StoragePolicy rows exist — previously these would NOT record. Now every enabled
    # camera is a recording candidate (schedule defaults to continuous when unscheduled).
    desired = {c.id for c in RecorderSupervisor()._desired_cameras()}
    assert cam_a.id in desired and cam_b.id in desired   # all enabled cameras record
    assert cam_off.id not in desired                     # disabled camera excluded


# ── manual record duration + auto-close + protect ────────────────────────────
def test_manual_duration_and_protect_api(client, mock_go2rtc):
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'M', 'host': '192.0.2.231', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']
    r = client.post(f"/api/v1/recording/cameras/{cam['uuid']}/manual/start", headers=h, json={'duration_s': 300})
    assert r.status_code == 200 and r.json['data']['planned_end_ts'] is not None
    # too-short duration rejected
    client.post(f"/api/v1/recording/cameras/{cam['uuid']}/manual/stop", headers=h, json={})
    assert client.post(f"/api/v1/recording/cameras/{cam['uuid']}/manual/start",
                       headers=h, json={'duration_s': 1}).status_code == 400
    # protect a recording
    rid = r.json['data']['recording_id']
    pr = client.post(f"/api/v1/recording/recordings/{rid}/protect", headers=h, json={'protected': True})
    assert pr.status_code == 200 and pr.json['data']['retention_class'] == 'protected'
    off = client.post(f"/api/v1/recording/recordings/{rid}/protect", headers=h, json={'protected': False})
    assert off.json['data']['retention_class'] == 'default'


def test_manual_autoclose_due(app_db):
    from datetime import timedelta
    from server.controller.recording import RecordingController
    from server.model.recording import CLASS_PROTECTED, REASON_MANUAL, Recording
    cam = _camera('ac')
    rec = Recording.create(cam.id, REASON_MANUAL, CLASS_PROTECTED, utcnow() - timedelta(minutes=10),
                           end_ts=None, planned_end_ts=utcnow() + timedelta(minutes=5))
    assert RecordingController.autoclose_due() == 0       # not yet due
    rec.planned_end_ts = utcnow() - timedelta(seconds=1)
    db.session.add(rec)
    db.session.commit()
    assert RecordingController.autoclose_due() == 1       # past planned end → closed
    assert Recording.get_by_id(rec.id).end_ts is not None


# ── role delete ──────────────────────────────────────────────────────────────
def test_role_delete_and_guards(client):
    h = login(client)
    rid = client.post('/api/v1/admin/roles', headers=h,
                      json={'name': 'tmp', 'display_name': 'Tmp', 'permissions': {}}).json['data']['id']
    assert client.delete(f'/api/v1/admin/roles/{rid}', headers=h).status_code == 200
    assert all(r['id'] != rid for r in client.get('/api/v1/admin/roles', headers=h).json['data'])
    # system role cannot be deleted
    sysrole = next(r for r in client.get('/api/v1/admin/roles', headers=h).json['data'] if r['is_system'])
    assert client.delete(f"/api/v1/admin/roles/{sysrole['id']}", headers=h).status_code == 400
