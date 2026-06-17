"""P10 — access control (doors, credentials, swipe decisions, access events).

Door hardware is mocked (controller_type='mock'). Tested: the decision matrix, the swipe
flow (log + unlock-on-grant + P3 access event), PIN factor, manual unlock, and the API.
Flag `access_control` defaults OFF.
"""
from datetime import timedelta

from server.model import db, utcnow
from server.model.access_credential import AccessCredential
from server.model.access_event import DECISION_DENIED, DECISION_GRANTED, AccessEvent
from server.model.camera import Camera
from server.model.door import STATE_UNLOCKED, Door
from server.model.event import TYPE_ACCESS, Event
from tests.conftest import login


def _door(group='default', require_pin=False, camera_id=None, enabled=True) -> Door:
    d = Door.create({'name': 'Front', 'controller_type': 'mock', 'access_group': group,
                     'require_pin': require_pin, 'camera_id': camera_id})
    if not enabled:
        d.modify({'enabled': False})
    return d


def _cred(card='CARD1', group='default', pin=None, enabled=True, valid_until=None) -> AccessCredential:
    c = AccessCredential.create({'card_number': card, 'holder_name': 'Alice', 'access_group': group,
                                 'pin': pin, 'valid_until': valid_until})
    if not enabled:
        c.modify({'enabled': False})
    return c


def _enable(monkeypatch):
    from server.service import feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: key == 'access_control')


# ── decision matrix ───────────────────────────────────────────────────────────
def test_evaluate_granted(app_db):
    from server.service import access_control
    _cred('C1', 'default')
    assert access_control.evaluate(_door('default'), 'C1')['decision'] == DECISION_GRANTED


def test_evaluate_denials(app_db):
    from server.service import access_control as ac
    door = _door('staff')
    _cred('OK', 'staff')
    assert ac.evaluate(door, 'NOPE')['reason'] == 'unknown_card'
    _cred('WRONG', 'visitor')
    assert ac.evaluate(door, 'WRONG')['reason'] == 'wrong_group'
    _cred('OFF', 'staff', enabled=False)
    assert ac.evaluate(door, 'OFF')['reason'] == 'card_disabled'
    _cred('EXP', 'staff', valid_until=utcnow() - timedelta(days=1))
    assert ac.evaluate(door, 'EXP')['reason'] == 'expired'
    assert ac.evaluate(_door('staff', enabled=False), 'OK')['reason'] == 'door_disabled'


def test_evaluate_public_group_allows_any(app_db):
    from server.service import access_control
    _cred('ANY', 'visitor')
    assert access_control.evaluate(_door('public'), 'ANY')['decision'] == DECISION_GRANTED


def test_pin_factor(app_db):
    from server.service import access_control
    door = _door('default', require_pin=True)
    _cred('PINNED', 'default', pin='1234')
    assert access_control.evaluate(door, 'PINNED', pin='9999')['reason'] == 'bad_pin'
    assert access_control.evaluate(door, 'PINNED', pin='1234')['decision'] == DECISION_GRANTED


def test_type_registered():
    from server.service.event_normalizer import VALID_TYPES
    assert TYPE_ACCESS in VALID_TYPES


# ── swipe flow ────────────────────────────────────────────────────────────────
def test_process_swipe_grant_unlocks_and_logs(app_db):
    from server.service import access_control
    door = _door('default')
    _cred('GO', 'default')
    res = access_control.process_swipe(door, 'GO', source='reader')
    assert res['granted'] is True and res['decision'] == DECISION_GRANTED
    assert Door.get_by_id(door.id).lock_state == STATE_UNLOCKED
    assert AccessEvent.recent(door_id=door.id)[0].decision == DECISION_GRANTED


def test_process_swipe_deny_keeps_locked(app_db):
    from server.service import access_control
    door = _door('default')
    res = access_control.process_swipe(door, 'GHOST')
    assert res['granted'] is False
    assert Door.get_by_id(door.id).lock_state == 'locked'
    assert AccessEvent.recent(door_id=door.id)[0].reason == 'unknown_card'


def test_swipe_raises_access_event_when_camera_linked(app_db, mock_go2rtc):
    from server.service import access_control
    cam = Camera()
    cam.name, cam.host, cam.vendor, cam.driver, cam.is_enabled = 'c', 'h', 'onvif', 'onvif', True
    db.session.add(cam)
    db.session.commit()
    door = _door('default', camera_id=cam.id)
    _cred('CAMCARD', 'default')
    access_control.process_swipe(door, 'CAMCARD')
    evs = db.session.query(Event).filter(Event.camera_id == cam.id, Event.type == TYPE_ACCESS).all()
    assert len(evs) == 1 and evs[0].subtype == DECISION_GRANTED


def test_manual_unlock(app_db):
    from server.service import access_control
    door = _door('default')
    access_control.unlock_door(door, source='manual')
    assert Door.get_by_id(door.id).lock_state == STATE_UNLOCKED
    assert AccessEvent.recent(door_id=door.id)[0].reason == 'manual_unlock'


# ── API ───────────────────────────────────────────────────────────────────────
def test_door_and_credential_crud_api(client, mock_go2rtc, monkeypatch):
    _enable(monkeypatch)
    h = login(client)
    did = client.post('/api/v1/access/doors', headers=h, json={'name': 'Lobby', 'access_group': 'staff'}).json['data']['id']
    assert len(client.get('/api/v1/access/doors', headers=h).json['data']['items']) == 1
    r = client.post('/api/v1/access/credentials', headers=h,
                    json={'card_number': 'B100', 'holder_name': 'Bob', 'access_group': 'staff', 'pin': '4321'})
    assert r.status_code == 200 and r.json['data']['has_pin'] is True and 'pin' not in r.json['data']
    # duplicate card rejected
    assert client.post('/api/v1/access/credentials', headers=h,
                       json={'card_number': 'B100', 'holder_name': 'X'}).status_code == 400
    # swipe via API → granted + access event logged
    sw = client.post(f'/api/v1/access/doors/{did}/swipe', headers=h, json={'card_number': 'B100', 'pin': '4321'})
    assert sw.status_code == 200 and sw.json['data']['granted'] is True
    assert len(client.get('/api/v1/access/events', headers=h).json['data']['items']) == 1
    # manual unlock
    assert client.post(f'/api/v1/access/doors/{did}/unlock', headers=h).status_code == 200


def test_access_available_by_default(client, mock_go2rtc):
    # access_control is now always-on (config-driven; hidden from the feature-flag list) —
    # the doors API is reachable; you "activate" it by adding doors/credentials.
    h = login(client)
    assert client.get('/api/v1/access/doors', headers=h).status_code == 200
