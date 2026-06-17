"""P4 services: geometry/label_map (pure), config resolver, ingest, search, trigger engine,
scheduler, node registry, scoped node tokens."""
from datetime import timedelta

import pytest

from server.model import db, utcnow
from server.model.ai_node import KIND_REMOTE, STATUS_OFFLINE, STATUS_ONLINE, AiNode
from server.model.ai_settings import AiSettings
from server.model.camera import Camera
from server.model.detection import Detection
from server.model.detection_assignment import DetectionAssignment
from server.model.detection_zone import DetectionZone
from server.model.event import Event
from server.model.object_trigger import ObjectTrigger
from server.service import (
    ai_config_resolver,
    ai_node_registry,
    ai_scheduler,
    detection_ingest,
    detection_search,
    geometry,
    label_map,
    object_trigger_engine,
)
from server.service.token import TokenService


# ── helpers ─────────────────────────────────────────────────────────────────
def _camera(name='cam') -> Camera:
    c = Camera()
    c.name = name
    c.host = 'h'
    c.vendor = 'onvif'
    c.driver = 'onvif'
    c.is_enabled = True
    db.session.add(c)
    db.session.commit()
    return c


def _node(name, gpu=False, cap=4, online=True) -> AiNode:
    n = AiNode.create(name=name, kind=KIND_REMOTE)
    n.update(gpu=gpu, capacity=cap, status=STATUS_ONLINE if online else STATUS_OFFLINE)
    return n


def _det(node, cam_id, **over):
    rep = {'camera_id': cam_id, 'class_id': 0, 'confidence': 0.9, 'bbox': [0.1, 0.2, 0.3, 0.4], 'epoch': 1}
    rep.update(over)
    return detection_ingest.ingest_batch(node, [rep])


# ── geometry / label_map (pure) ──────────────────────────────────────────────
def test_point_in_polygon_and_bottom_center():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert geometry.point_in_polygon(0.5, 0.5, sq)
    assert not geometry.point_in_polygon(1.5, 0.5, sq)
    bx, by = geometry.bottom_center([0.2, 0.1, 0.4, 0.9])
    assert bx == pytest.approx(0.3) and by == pytest.approx(0.9)


def test_label_map():
    assert label_map.normalize(0, None) == (0, 'person')
    assert label_map.normalize(None, 'truck') == (7, 'truck')
    assert label_map.normalize(None, 'unicorn') is None
    assert label_map.class_ids_for(['person', 'dog']) == [0, 16]


# ── config resolver ──────────────────────────────────────────────────────────
def test_effective_settings_camera_override(app_db):
    cam = _camera()
    AiSettings.upsert(cam.id, {'target_fps': 2, 'model': 'yolov8m'})
    eff = ai_config_resolver.effective_settings(cam.id)
    assert eff['target_fps'] == 2 and eff['model'] == 'yolov8m'
    assert ai_config_resolver.effective_settings(99999)['target_fps'] == 5      # global default


# ── node tokens ──────────────────────────────────────────────────────────────
def test_node_token_roundtrip(app_db):
    node = AiNode.create(name='n', kind=KIND_REMOTE)
    tok = TokenService.issue_node_token(node.uuid)
    claims = TokenService.verify_node_token(tok['token'])
    assert claims['sub'] == node.uuid and claims['aud'] == 'node'


def test_join_token_one_time(app_db):
    jt = TokenService.issue_join_token(12345)
    assert TokenService.consume_join_token(jt) == 12345
    with pytest.raises(Exception):
        TokenService.consume_join_token(jt)            # already burned


def test_node_join_issues_token(app_db):
    node = AiNode.create(name='n', kind=KIND_REMOTE)
    res = ai_node_registry.join(node.id, {'gpu': True, 'capacity': 5, 'capabilities': {'models': ['yolov8n']}})
    assert res['node_token'] and res['heartbeat_interval_s'] > 0
    n2 = AiNode.get_by_id(node.id)
    assert n2.status == STATUS_ONLINE and n2.gpu and n2.capacity == 5 and n2.token_jti


# ── ingest ───────────────────────────────────────────────────────────────────
def test_ingest_requires_assignment(app_db):
    node, cam = _node('n1'), _camera()
    res = _det(node, cam.id)
    assert res['accepted'] == 0 and res['rejected'][0]['reason'] == 'not_assigned'


def test_ingest_normalizes(app_db):
    node, cam = _node('n1'), _camera()
    DetectionAssignment.assign(cam.id, node.id)        # epoch 1
    res = _det(node, cam.id, confidence=0.91, bytetrack_id=7)
    assert res['accepted'] == 1
    total, rows = Detection.search(camera_ids=[cam.id])
    d = rows[0]
    assert total == 1 and d.label == 'person' and d.confidence == 91 and d.track_key and d.track_id


def test_ingest_stale_epoch_rejected(app_db):
    node, cam = _node('n1'), _camera()
    DetectionAssignment.assign(cam.id, node.id)        # epoch 1
    res = _det(node, cam.id, epoch=99)
    assert res['accepted'] == 0 and res['rejected'][0]['reason'] == 'stale_epoch'


def test_ingest_zone_attribution(app_db):
    node, cam = _node('n1'), _camera()
    DetectionAssignment.assign(cam.id, node.id)
    z = DetectionZone.create(cam.id, {'name': 'left', 'kind': 'include',
                                      'polygon': [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]})
    _det(node, cam.id, bbox=[0.1, 0.1, 0.3, 0.4])      # bottom-center (0.2,0.4) ∈ left
    _, rows = Detection.search(camera_ids=[cam.id])
    assert str(rows[0].zone_id) == str(z.id)


# ── search ───────────────────────────────────────────────────────────────────
def test_search_clip_grouping(app_db):
    cam = _camera()
    base = utcnow()
    rows = [{'camera_id': cam.id, 'ts': base + timedelta(seconds=i), 'class_id': 0, 'label': 'person',
             'confidence': 80, 'bbox': [0.1, 0.1, 0.2, 0.2], 'track_id': 1, 'track_key': 'a' * 32}
            for i in range(3)]
    rows.append({'camera_id': cam.id, 'ts': base + timedelta(minutes=5), 'class_id': 0, 'label': 'person',
                 'confidence': 70, 'bbox': [0.1, 0.1, 0.2, 0.2], 'track_id': 2, 'track_key': 'b' * 32})
    Detection.bulk_create(rows)
    res = detection_search.search(camera_ids=[cam.id], group='clip')
    assert res['count'] == 2                            # 30s gap → two clips
    assert res['items'][0]['labels'] == ['person']


# ── trigger engine ───────────────────────────────────────────────────────────
def test_trigger_fires_object_event(app_db):
    cam = _camera()
    ObjectTrigger.create({'camera_id': cam.id, 'name': 'person', 'labels': ['person'], 'min_confidence': 50})
    ev = object_trigger_engine.evaluate(
        {'camera_id': cam.id, 'label': 'person', 'confidence': 80, 'bbox': [0.1, 0.1, 0.2, 0.2], 'track_key': 't1'})
    assert ev is not None
    total, rows = Event.get_list(camera_ids=[cam.id])
    assert total >= 1 and rows[0].type == 'object'


def test_trigger_cooldown_suppresses(app_db):
    cam = _camera()
    ObjectTrigger.create({'camera_id': cam.id, 'name': 'p', 'labels': ['person'], 'min_confidence': 50,
                          'cooldown_s': 60, 'debounce_per_track': False})
    e1 = object_trigger_engine.evaluate({'camera_id': cam.id, 'label': 'person', 'confidence': 80,
                                         'bbox': [0, 0, 0.1, 0.1], 'track_key': 't1'})
    e2 = object_trigger_engine.evaluate({'camera_id': cam.id, 'label': 'person', 'confidence': 80,
                                         'bbox': [0, 0, 0.1, 0.1], 'track_key': 't2'})
    assert e1 is not None and e2 is None


def test_trigger_below_confidence(app_db):
    cam = _camera()
    ObjectTrigger.create({'camera_id': cam.id, 'name': 'p', 'labels': ['person'], 'min_confidence': 70})
    assert object_trigger_engine.evaluate(
        {'camera_id': cam.id, 'label': 'person', 'confidence': 50, 'bbox': [0, 0, 0.1, 0.1], 'track_key': 't'}) is None


# ── scheduler ────────────────────────────────────────────────────────────────
def test_rebalance_bin_packing(app_db):
    n1, n2 = _node('n1', cap=2), _node('n2', cap=2)
    cams = [_camera('c%d' % i) for i in range(3)]
    res = ai_scheduler.rebalance()
    assert res['assigned'] == 3 and res['pending_count'] == 0
    for c in cams:
        assert DetectionAssignment.get_for_camera(c.id) is not None
    loads = sorted([len(DetectionAssignment.for_node(n1.id)), len(DetectionAssignment.for_node(n2.id))])
    assert loads == [1, 2]


def test_rebalance_overflow_pending(app_db):
    _node('n1', cap=1)
    [_camera('c%d' % i) for i in range(3)]
    res = ai_scheduler.rebalance()
    assert res['assigned'] == 1 and res['pending_count'] == 2


def test_reassign_on_node_offline(app_db):
    n1, n2 = _node('n1', cap=4), _node('n2', cap=4)
    cams = [_camera('c%d' % i) for i in range(2)]
    ai_scheduler.rebalance()
    n1.update(status=STATUS_OFFLINE)
    ai_scheduler.rebalance()
    for c in cams:
        a = DetectionAssignment.get_for_camera(c.id)
        assert a is not None and str(a.node_id) == str(n2.id)


def test_rebalance_keeps_existing(app_db):
    n1 = _node('n1', cap=4)
    cam = _camera()
    ai_scheduler.rebalance()
    a1 = DetectionAssignment.get_for_camera(cam.id)
    epoch1 = a1.epoch
    ai_scheduler.rebalance()                            # idempotent — no movement
    a2 = DetectionAssignment.get_for_camera(cam.id)
    assert a2.epoch == epoch1 and str(a2.node_id) == str(n1.id)
