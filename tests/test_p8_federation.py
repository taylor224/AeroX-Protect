"""P8 — multi-NVR federation (hub aggregating member NVRs).

The member API client (HTTP to /api/v1/ext/*) is mocked. Tested: client parsing + error
mapping, member token encryption, sync caching + status, aggregation, and the API
(member CRUD with write-only token, sync, aggregated views). Flag `federation` defaults OFF.
"""
from types import SimpleNamespace

from server.model import db
from server.model.federation_camera import FederationCamera
from server.model.federation_member import STATUS_OFFLINE, STATUS_ONLINE, FederationMember
from tests.conftest import login


def _member(name='Site B', url='https://site-b.example.com', token='tok-123') -> FederationMember:
    return FederationMember.create(name=name, base_url=url, token=token)


# ── client parsing / error mapping ───────────────────────────────────────────
def test_client_parses_and_maps_errors(monkeypatch):
    from server.driver import federation as drv
    monkeypatch.setattr(drv, '_guard_url', lambda url: None)

    def fake_get(url, headers=None, params=None, timeout=None, allow_redirects=True):
        if url.endswith('/ext/state'):
            return SimpleNamespace(status_code=200, is_redirect=False, json=lambda: {'data': {'cameras': [{'uuid': 'a', 'name': 'Cam A', 'online': True}]}})
        if url.endswith('/ext/events'):
            return SimpleNamespace(status_code=200, is_redirect=False, json=lambda: {'data': {'items': [{'id': '1', 'start_ts': 10}]}})
        return SimpleNamespace(status_code=401, is_redirect=False, json=lambda: {})
    monkeypatch.setattr(drv.requests, 'get', fake_get)

    c = drv.FederationClient('https://m.example.com', 'tok')
    assert c.state()['cameras'][0]['name'] == 'Cam A'
    assert c.list_events()[0]['start_ts'] == 10

    # 401 → FederationError unauthorized
    monkeypatch.setattr(drv.requests, 'get',
                        lambda *a, **k: SimpleNamespace(status_code=401, is_redirect=False, json=lambda: {}))
    try:
        c.state()
        assert False
    except drv.FederationError as e:
        assert 'unauthorized' in str(e)


# ── member model: token encryption ───────────────────────────────────────────
def test_member_token_encrypted_and_hidden(app_db):
    m = _member(token='secret-token')
    assert m.has_token and m.get_token() == 'secret-token'
    d = m.to_dict()
    assert d['has_token'] is True and 'token' not in d and 'token_enc' not in d


# ── sync: cache + status ──────────────────────────────────────────────────────
def test_sync_member_caches_cameras(app_db, monkeypatch):
    from server.service import federation
    m = _member()
    stub = SimpleNamespace(state=lambda: {'cameras': [
        {'uuid': 'r1', 'name': 'Front', 'online': True, 'status': 'online'},
        {'uuid': 'r2', 'name': 'Back', 'online': False, 'status': 'offline'}]})
    monkeypatch.setattr(federation, '_client', lambda member: stub)

    res = federation.sync_member(m.id)
    assert res == {'ok': True, 'cameras': 2}
    m = FederationMember.get_by_id(m.id)
    assert m.status == STATUS_ONLINE and m.camera_count == 2
    cams = FederationCamera.for_members([m.id])
    assert {c.name for c in cams} == {'Front', 'Back'}


def test_sync_member_marks_offline_on_error(app_db, monkeypatch):
    from server.driver.federation import FederationError
    from server.service import federation
    m = _member()

    def boom():
        raise FederationError('unreachable: timeout')
    monkeypatch.setattr(federation, '_client', lambda member: SimpleNamespace(state=boom))

    res = federation.sync_member(m.id)
    assert res['ok'] is False
    assert FederationMember.get_by_id(m.id).status == STATUS_OFFLINE


# ── aggregation ───────────────────────────────────────────────────────────────
def test_aggregate_cameras_and_events(app_db, monkeypatch):
    from server.service import federation
    m1, m2 = _member('A'), _member('B', url='https://b.example.com')
    FederationCamera.replace_for_member(m1.id, [{'uuid': 'a1', 'name': 'A-Cam', 'online': True}])
    FederationCamera.replace_for_member(m2.id, [{'uuid': 'b1', 'name': 'B-Cam', 'online': True}])

    cams = federation.aggregate_cameras()
    assert {c['member_name'] for c in cams} == {'A', 'B'}

    events = {m1.id: [{'id': '1', 'start_ts': 100}], m2.id: [{'id': '2', 'start_ts': 200}]}
    monkeypatch.setattr(federation, '_client',
                        lambda member: SimpleNamespace(list_events=lambda params=None: events[member.id]))
    merged = federation.aggregate_events()
    assert [e['id'] for e in merged] == ['2', '1']            # sorted by ts desc, member-tagged
    assert merged[0]['member_name'] == 'B'


# ── API ───────────────────────────────────────────────────────────────────────
def test_member_crud_api(client, mock_go2rtc, monkeypatch):
    from server.service import feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    h = login(client)
    r = client.post('/api/v1/federation/members', headers=h,
                    json={'name': 'Site C', 'base_url': 'https://c.example.com', 'token': 'abc'})
    assert r.status_code == 200, r.json
    assert r.json['data']['has_token'] is True and 'token' not in r.json['data']
    mid = r.json['data']['id']
    # invalid (missing token) rejected
    assert client.post('/api/v1/federation/members', headers=h,
                       json={'name': 'X', 'base_url': 'https://x.example.com'}).status_code == 400
    assert len(client.get('/api/v1/federation/members', headers=h).json['data']['items']) == 1
    # aggregated views respond
    assert client.get('/api/v1/federation/cameras', headers=h).status_code == 200
    client.delete(f'/api/v1/federation/members/{mid}', headers=h)
    assert client.get('/api/v1/federation/members', headers=h).json['data']['items'] == []


def test_sync_endpoint(client, mock_go2rtc, monkeypatch):
    from server.service import feature_flag, federation
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    monkeypatch.setattr(federation, '_client',
                        lambda member: SimpleNamespace(state=lambda: {'cameras': [{'uuid': 'z', 'name': 'Z'}]}))
    h = login(client)
    mid = client.post('/api/v1/federation/members', headers=h,
                      json={'name': 'S', 'base_url': 'https://s.example.com', 'token': 't'}).json['data']['id']
    r = client.post(f'/api/v1/federation/members/{mid}/sync', headers=h)
    assert r.status_code == 200, r.json
    assert r.json['data']['sync']['ok'] is True and r.json['data']['camera_count'] == 1
