"""P7 A7 — license-plate recognition (reads + watchlist + lpr events).

A real plate-OCR model runs on the node; the server ingests reads. Tested here: text
normalization + confusable folding, watchlist matching, the node ingest→plate_reads→
deny-watchlist→`lpr` event path, and the read/watchlist API. Event raising is gated
per-camera by `ai_features.lpr` (off by default); the watchlist is global config.
"""
from server.model import db
from server.model.camera import Camera
from server.model.ai_node import KIND_REMOTE, STATUS_ONLINE, AiNode
from server.model.detection_assignment import DetectionAssignment
from server.model.event import TYPE_LPR, Event
from server.model.plate_list import KIND_ALLOW, KIND_DENY, PlateListEntry
from server.model.plate_read import PlateRead
from tests.conftest import login


def _camera(name='lprcam', ai=None) -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    if ai:
        c.ai_features = ai
    db.session.add(c)
    db.session.commit()
    return c


def _node(name='ln1') -> AiNode:
    n = AiNode.create(name=name, kind=KIND_REMOTE)
    n.update(status=STATUS_ONLINE)
    return n


# ── normalization ────────────────────────────────────────────────────────────
def test_plate_normalize_and_fold():
    from server.service import plate_normalize
    assert plate_normalize.normalize(' 12-가 3456 ') == '123456'      # strip non-alnum (Korean dropped)
    assert plate_normalize.normalize('ab 12 cd') == 'AB12CD'
    # confusable folding: O↔0, I↔1, B↔8 collapse so OCR slips still match
    assert plate_normalize.match_key('O0I1') == plate_normalize.match_key('0011')
    assert plate_normalize.match_key('B8') == '88'


# ── watchlist matching ───────────────────────────────────────────────────────
def test_watchlist_match_deny_wins(app_db):
    from server.service import plate_normalize
    PlateListEntry.create(plate_text='ALLOW1', plate_key=plate_normalize.match_key('ALLOW1'), kind=KIND_ALLOW)
    PlateListEntry.create(plate_text='DENY1', plate_key=plate_normalize.match_key('DENY1'), kind=KIND_DENY)
    assert PlateListEntry.match(plate_normalize.match_key('deny1')).kind == KIND_DENY
    assert PlateListEntry.match(plate_normalize.match_key('nope')) is None


def test_type_registered():
    from server.service.event_normalizer import VALID_TYPES
    assert TYPE_LPR in VALID_TYPES


# ── worker report builder ────────────────────────────────────────────────────
def test_build_report_filters_low_conf():
    from worker.detector import lpr
    assert lpr.build_report(1, '12가3456', 90, region=[0, 0, 1, 1], ts_ms=123) ['plate_text'] == '12가3456'
    assert lpr.build_report(1, '12가3456', 20) is None       # below floor
    assert lpr.build_report(1, '', 99) is None               # empty


# ── ingest ───────────────────────────────────────────────────────────────────
def test_ingest_requires_assignment(app_db):
    from server.service import lpr_ingest
    node, cam = _node(), _camera(ai={'lpr': True})
    res = lpr_ingest.ingest_batch(node, [{'camera_id': cam.id, 'plate_text': 'ABC123', 'confidence': 90}])
    assert res['accepted'] == 0 and res['rejected'][0]['reason'] == 'not_assigned'


def test_ingest_stores_and_raises_on_deny(app_db):
    from server.service import lpr_ingest, plate_normalize
    node, cam = _node(), _camera(ai={'lpr': True})   # per-camera AI enable
    DetectionAssignment.assign(cam.id, node.id)
    PlateListEntry.create(plate_text='STOLEN9', plate_key=plate_normalize.match_key('STOLEN9'),
                          kind=KIND_DENY, label='stolen')
    res = lpr_ingest.ingest_batch(node, [
        {'camera_id': cam.id, 'plate_text': 'STOLEN9', 'confidence': 88, 'region': [0.1, 0.1, 0.3, 0.2]},
        {'camera_id': cam.id, 'plate_text': 'RANDOM1', 'confidence': 80},   # no match
        {'camera_id': cam.id, 'plate_text': 'lo', 'confidence': 20},        # low conf → rejected
    ])
    assert res['accepted'] == 2 and res['matched'] == 1
    reads = PlateRead.recent_for_camera(cam.id)
    hit = next(r for r in reads if r.plate_key == 'STOLEN9')
    assert hit.list_kind == KIND_DENY and hit.list_id is not None
    evs = db.session.query(Event).filter(Event.camera_id == cam.id, Event.type == TYPE_LPR).all()
    assert len(evs) == 1 and evs[0].subtype == KIND_DENY


def test_ingest_feature_off_stores_no_match(app_db):
    """Camera without ai_features.lpr → reads stored, but no watchlist match/event."""
    from server.service import lpr_ingest, plate_normalize
    node, cam = _node(), _camera()                   # lpr off (default)
    DetectionAssignment.assign(cam.id, node.id)
    PlateListEntry.create(plate_text='STOLEN9', plate_key=plate_normalize.match_key('STOLEN9'), kind=KIND_DENY)
    res = lpr_ingest.ingest_batch(node, [{'camera_id': cam.id, 'plate_text': 'STOLEN9', 'confidence': 88}])
    assert res['accepted'] == 1 and res['matched'] == 0      # stored, but no watchlist match/event
    assert db.session.query(Event).filter(Event.type == TYPE_LPR).count() == 0


# ── API ──────────────────────────────────────────────────────────────────────
def test_watchlist_crud_and_reads_api(client, mock_go2rtc, monkeypatch):
    from server.service import feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    h = login(client)
    # create a watchlist entry
    r = client.post('/api/v1/plate-lists', headers=h, json={'plate_text': '12GA3456', 'kind': 'deny', 'label': 'test'})
    assert r.status_code == 200, r.json
    eid = r.json['data']['id']
    assert client.get('/api/v1/plate-lists', headers=h).json['data']['items'][0]['kind'] == 'deny'
    # duplicate rejected
    assert client.post('/api/v1/plate-lists', headers=h, json={'plate_text': '12GA3456'}).status_code == 400
    # update + delete
    client.put(f'/api/v1/plate-lists/{eid}', headers=h, json={'enabled': False})
    client.delete(f'/api/v1/plate-lists/{eid}', headers=h)
    assert client.get('/api/v1/plate-lists', headers=h).json['data']['items'] == []
    # camera reads + search endpoints respond
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'C', 'host': '192.0.2.210', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']
    assert client.get(f"/api/v1/cameras/{cam['uuid']}/plates", headers=h).json['data']['items'] == []
    assert client.get('/api/v1/plates/search?q=123', headers=h).status_code == 200
