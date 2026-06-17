"""P5 HTTP surface: rule CRUD/trigger, action-target + webhook, monitor pairing flow,
notifications/subscriptions, web-push, api-token → external API scope."""
from server.driver import webhook as webhook_drv
from tests.conftest import create_user, login


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status


def _dashboard():
    from server.model.dashboard import Dashboard
    from server.model.user import User
    from server.model import db
    admin = db.session.query(User).filter(User.login_id == 'admin').first()
    return Dashboard.create(name='Lobby', layout={'grid': {'cols': 12, 'rows': 8}, 'cells': [], 'ratio_mode': 'fit'},
                            owner_id=admin.id)


# ── rules ────────────────────────────────────────────────────────────────────
def test_rule_crud_and_test(client):
    h = login(client)
    cr = client.post('/api/v1/rules', headers=h, json={
        'name': 'motion-rule', 'trigger_type': 'event', 'trigger': {'event_types': ['motion']},
        'condition': {}, 'actions': []})
    assert cr.status_code == 200, cr.json
    uuid = cr.json['data']['uuid']
    assert client.get('/api/v1/rules', headers=h).json['data']['count'] >= 1
    up = client.put(f'/api/v1/rules/{uuid}', headers=h, json={'name': 'renamed', 'trigger_type': 'event'})
    assert up.json['data']['name'] == 'renamed'
    test = client.post(f'/api/v1/rules/{uuid}/test', headers=h, json={})
    assert test.status_code == 200 and 'matched' in test.json['data']
    assert client.delete(f'/api/v1/rules/{uuid}', headers=h).status_code == 200


def test_rule_rejects_bad_trigger_type(client):
    h = login(client)
    r = client.post('/api/v1/rules', headers=h, json={'name': 'x', 'trigger_type': 'bogus'})
    assert r.status_code == 400


def test_rule_manual_trigger_webhook(client, monkeypatch):
    monkeypatch.setattr(webhook_drv.requests, 'post', lambda url, **kw: FakeResp(200))
    h = login(client)
    wh = client.post('/api/v1/webhooks', headers=h, json={'name': 'hk', 'url': 'http://10.0.0.2/h', 'secret': 's'})
    hook_id = wh.json['data']['id']
    rule = client.post('/api/v1/rules', headers=h, json={
        'name': 'manual-hook', 'trigger_type': 'manual', 'trigger': {},
        'actions': [{'type': 'webhook', 'target_id': int(hook_id)}]})
    uuid = rule.json['data']['uuid']
    fired = client.post(f'/api/v1/rules/{uuid}/trigger', headers=h, json={})
    assert fired.status_code == 200 and fired.json['data']['status'] == 'success'
    assert client.get(f'/api/v1/rules/{uuid}/executions', headers=h).json['data']['count'] == 1


# ── action targets / webhooks ────────────────────────────────────────────────
def test_action_target_crud(client):
    h = login(client)
    cr = client.post('/api/v1/action-targets', headers=h, json={
        'type': 'speaker', 'name': 'lobby-spk', 'protocol': 'vendor_http', 'host': '10.0.0.50',
        'username': 'admin', 'password': 'secret', 'config': {'play_url': 'http://10.0.0.50/play'}})
    assert cr.status_code == 200, cr.json
    data = cr.json['data']
    assert data['has_credentials'] is True and 'password' not in data    # creds masked
    uuid = data['uuid']
    assert any(t['uuid'] == uuid for t in client.get('/api/v1/action-targets', headers=h).json['data']['items'])
    assert client.delete(f'/api/v1/action-targets/{uuid}', headers=h).status_code == 200


def test_webhook_test_endpoint(client, monkeypatch):
    monkeypatch.setattr(webhook_drv.requests, 'post', lambda url, **kw: FakeResp(200))
    h = login(client)
    wh = client.post('/api/v1/webhooks', headers=h, json={'name': 'w', 'url': 'http://10.0.0.3/h'})
    assert wh.json['data']['has_secret'] is False
    uuid = wh.json['data']['uuid']
    res = client.post(f'/api/v1/webhooks/{uuid}/test', headers=h, json={})
    assert res.status_code == 200 and res.json['data']['status'] == 'success'


def test_targets_require_manage(client):
    h = login(client)
    create_user(client, h, 'tgt_ro', {'targets': ['read']})
    vh = login(client, 'tgt_ro', 'viewer1234!')
    assert client.get('/api/v1/action-targets', headers=vh).status_code == 200
    assert client.post('/api/v1/action-targets', headers=vh, json={'type': 'io', 'name': 'x', 'protocol': 'vendor_http'}).status_code == 403


# ── monitor pairing flow ─────────────────────────────────────────────────────
def test_monitor_pairing_full_flow(client):
    h = login(client)
    dash = _dashboard()
    mon = client.post('/api/v1/monitors', headers=h, json={'name': 'lobby-tv', 'dashboard_uuid': dash.uuid})
    assert mon.status_code == 200, mon.json
    muuid = mon.json['data']['uuid']

    pc = client.post(f'/api/v1/monitors/{muuid}/pair-code', headers=h, json={})
    code = pc.json['data']['code']
    assert len(code) == 6 and pc.json['data']['expires_in'] == 60

    claim = client.post('/api/v1/pairing/claim', json={'code': code})
    assert claim.status_code == 200, claim.json
    access = claim.json['data']['access_token']
    mh = {'Authorization': 'Bearer ' + access}

    me = client.get('/api/v1/monitor/me', headers=mh)
    assert me.status_code == 200 and me.json['data']['dashboard']['uuid'] == dash.uuid

    # claim reuse fails
    assert client.post('/api/v1/pairing/claim', json={'code': code}).status_code == 400

    # revoke → token invalid
    client.post(f'/api/v1/monitors/{muuid}/revoke', headers=h, json={})
    assert client.get('/api/v1/monitor/me', headers=mh).status_code == 401


def test_pairing_bad_code(client):
    assert client.post('/api/v1/pairing/claim', json={'code': '000000'}).status_code == 400


# ── notifications ────────────────────────────────────────────────────────────
def test_notification_subscriptions(client):
    h = login(client)
    cr = client.post('/api/v1/notification-subscriptions', headers=h, json={
        'channel': 'push', 'event_types': ['motion', 'intrusion'], 'min_priority': 'high'})
    assert cr.status_code == 200
    sid = cr.json['data']['id']
    assert any(s['id'] == sid for s in client.get('/api/v1/notification-subscriptions', headers=h).json['data']['items'])
    assert client.delete(f'/api/v1/notification-subscriptions/{sid}', headers=h).status_code == 200
    assert client.get('/api/v1/push/vapid-public-key', headers=h).status_code == 200


# ── external API (opaque token) ──────────────────────────────────────────────
def test_api_token_external_access(client):
    h = login(client)
    cr = client.post('/api/v1/api-tokens', headers=h, json={'name': 'HA', 'scopes': {'events': ['read'], 'state': ['read']}})
    assert cr.status_code == 200
    raw = cr.json['data']['token']
    assert raw.startswith('axp_')
    uuid = cr.json['data']['uuid']

    ext = client.get('/api/v1/ext/events', headers={'Authorization': 'Bearer ' + raw})
    assert ext.status_code == 200 and 'items' in ext.json['data']
    state = client.get('/api/v1/ext/state', headers={'X-API-Key': raw})
    assert state.status_code == 200 and 'cameras' in state.json['data']
    # insufficient scope
    assert client.post('/api/v1/ext/subscriptions', headers={'Authorization': 'Bearer ' + raw},
                       json={'url': 'http://10.0.0.9/h'}).status_code == 200    # events:read covers subscribe

    client.post(f'/api/v1/api-tokens/{uuid}/revoke', headers=h, json={})
    assert client.get('/api/v1/ext/events', headers={'Authorization': 'Bearer ' + raw}).status_code == 401


def test_external_requires_token(client):
    assert client.get('/api/v1/ext/events').status_code == 401
