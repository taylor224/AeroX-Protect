"""/api/v1/system update API: 501 without a launcher, permission gating, launcher
proxying, and the HMAC update ticket round-trip."""
import time

import config
from server.service import update_ticket
from tests.conftest import create_user, login


# ── update ticket ─────────────────────────────────────────────────────────────
def test_ticket_roundtrip():
    t = update_ticket.issue(ttl=60)
    assert update_ticket.verify(t['ticket'])


def test_ticket_expiry():
    t = update_ticket.issue(ttl=-10)
    assert not update_ticket.verify(t['ticket'])


def test_ticket_garbage_rejected():
    assert not update_ticket.verify('')
    assert not update_ticket.verify('nodot')
    assert not update_ticket.verify('123.%s' % ('a' * 43))
    exp = int(time.time()) + 60
    assert not update_ticket.verify('%d.tampered' % exp)


def test_ticket_matches_launcher_verifier():
    """The launcher re-implements verification stdlib-only — keep them in lockstep."""
    import importlib
    import pathlib
    import sys
    launcher_root = str(pathlib.Path(__file__).resolve().parents[1] / 'windows' / 'launcher')
    sys.path.insert(0, launcher_root)
    try:
        mod = importlib.import_module('axp_launcher.control')
    finally:
        sys.path.remove(launcher_root)
    t = update_ticket.issue(ttl=60)['ticket']
    assert mod._verify_ticket(config.SECRET_KEY, t)
    assert not mod._verify_ticket('other-secret', t)


# ── API gating ────────────────────────────────────────────────────────────────
def test_system_api_501_without_launcher(client):
    headers = login(client)
    assert config.LAUNCHER_URL is None
    for path in ('/system/update/check', '/system/update/status', '/system/services'):
        res = client.get('/api/v1' + path, headers=headers)
        assert res.status_code == 501, path
    res = client.post('/api/v1/system/update/apply', headers=headers, json={})
    assert res.status_code == 501


def test_system_api_requires_auth(client):
    assert client.get('/api/v1/system/update/check').status_code == 401


def test_apply_requires_settings_update_permission(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    admin = login(client)
    create_user(client, admin, 'viewer', {'settings': ['read']})
    viewer = login(client, 'viewer', 'viewer1234!')
    res = client.post('/api/v1/system/update/apply', headers=viewer, json={})
    assert res.status_code == 403


def test_check_proxies_launcher(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    from server.controller.system import SystemController
    monkeypatch.setattr(SystemController, '_request', classmethod(
        lambda cls, method, path, **kw: {'latest_version': '9.9.9', 'update_available': True}))
    headers = login(client)
    res = client.get('/api/v1/system/update/check', headers=headers)
    assert res.status_code == 200
    data = res.json['data']
    assert data['update_available'] is True
    assert data['current_version'] == config.VERSION


def test_apply_returns_ticket_and_poll_url(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    from server.controller.system import SystemController
    calls = []
    monkeypatch.setattr(SystemController, '_request', classmethod(
        lambda cls, method, path, **kw: calls.append((method, path)) or {}))
    headers = login(client)
    res = client.post('/api/v1/system/update/apply', headers=headers, json={'version': '9.9.9'})
    assert res.status_code == 200
    data = res.json['data']
    assert update_ticket.verify(data['ticket'])
    assert data['poll_url'] == '/updater/v1/update/status'
    assert ('POST', '/v1/update/apply') in calls


def test_apply_conflict_when_update_already_running(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    from server.controller.system import SystemController, UpdateAlreadyRunning

    def _raise(cls, method, path, **kw):
        raise UpdateAlreadyRunning()
    monkeypatch.setattr(SystemController, '_request', classmethod(_raise))
    headers = login(client)
    res = client.post('/api/v1/system/update/apply', headers=headers, json={})
    assert res.status_code == 409
    assert res.json['message'] == 'update_already_running'


def test_status_includes_ticket_while_running(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    from server.controller.system import SystemController
    monkeypatch.setattr(SystemController, '_request', classmethod(
        lambda cls, method, path, **kw: {'phase': 'downloading', 'percent': 40}))
    headers = login(client)
    res = client.get('/api/v1/system/update/status', headers=headers)
    assert res.status_code == 200
    data = res.json['data']
    assert update_ticket.verify(data['ticket'])
    assert data['poll_url'] == '/updater/v1/update/status'


def test_status_no_ticket_when_idle(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:10099')
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    from server.controller.system import SystemController
    monkeypatch.setattr(SystemController, '_request', classmethod(
        lambda cls, method, path, **kw: {'phase': 'idle', 'percent': 0}))
    headers = login(client)
    res = client.get('/api/v1/system/update/status', headers=headers)
    assert res.status_code == 200
    assert 'ticket' not in res.json['data']


def test_launcher_unreachable_maps_to_500(client, monkeypatch):
    monkeypatch.setattr(config, 'LAUNCHER_URL', 'http://127.0.0.1:1')   # closed port
    monkeypatch.setattr(config, 'LAUNCHER_TOKEN', 'tok')
    headers = login(client)
    res = client.get('/api/v1/system/update/check', headers=headers)
    assert res.status_code == 500
    assert res.json['message'] == 'launcher_unreachable'
