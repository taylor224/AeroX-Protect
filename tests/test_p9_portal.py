"""P9 — remote portal (TURN/STUN ICE servers for outside-LAN WebRTC).

The actual relay needs a coturn server; tested here is the deliverable: coturn-style
ephemeral HMAC credential generation, ICE-server assembly, config CRUD with an encrypted
write-only secret, and the API (ice-servers degrades to STUN when off). Flag default OFF.
"""
import base64
import hashlib
import hmac
from types import SimpleNamespace

from server.model.turn_config import TurnConfig
from tests.conftest import login


# ── ephemeral credentials (coturn REST-API scheme) ───────────────────────────
def test_ephemeral_credentials_hmac():
    from server.service import turn
    username, credential = turn.ephemeral_credentials(42, 'shared-secret', 3600)
    expiry_s, uid = username.split(':')
    assert uid == '42' and int(expiry_s) > 0
    expected = base64.b64encode(
        hmac.new(b'shared-secret', username.encode(), hashlib.sha1).digest()).decode()
    assert credential == expected             # verifiable by coturn with the same secret


# ── ICE server assembly ──────────────────────────────────────────────────────
def test_ice_servers_stun_only_when_disabled(app_db):
    from server.service import turn
    out = turn.ice_servers(SimpleNamespace(id=1))
    assert out['ice_servers'][0]['urls'] == 'stun:stun.l.google.com:19302'
    assert all('credential' not in s for s in out['ice_servers'])


def test_ice_servers_includes_turn_when_configured(app_db):
    from server.service import turn
    TurnConfig.update({'enabled': True, 'turn_host': 'turn.example.com', 'turn_port': 3478,
                       'turn_protocol': 'udp', 'auth_secret': 'sek', 'stun_urls': ['stun:s1:3478']})
    out = turn.ice_servers(SimpleNamespace(id=7))
    turn_entry = [s for s in out['ice_servers'] if 'credential' in s]
    assert len(turn_entry) == 1
    assert turn_entry[0]['urls'] == ['turn:turn.example.com:3478?transport=udp']
    assert turn_entry[0]['username'].endswith(':7') and turn_entry[0]['credential']


# ── config model: secret encryption ──────────────────────────────────────────
def test_config_secret_encrypted_and_hidden(app_db):
    cfg = TurnConfig.update({'auth_secret': 'topsecret', 'turn_host': 'h'})
    assert cfg.has_secret and cfg.get_secret() == 'topsecret'
    d = cfg.to_dict()
    assert d['has_secret'] is True and 'auth_secret' not in d and 'auth_secret_enc' not in d


# ── API ───────────────────────────────────────────────────────────────────────
def test_ice_servers_endpoint_degrades_to_stun(client, mock_go2rtc):
    h = login(client)
    r = client.get('/api/v1/portal/ice-servers', headers=h)   # flag OFF by default
    assert r.status_code == 200, r.json
    assert r.json['data']['ice_servers'][0]['urls'].startswith('stun:')
    assert r.json['data']['ttl'] == 0


def test_config_crud_api(client, mock_go2rtc):
    h = login(client)
    # portal config is available by default (gated by portal:manage permission, no flag)
    assert client.get('/api/v1/portal/config', headers=h).status_code == 200
    up = client.put('/api/v1/portal/config', headers=h, json={
        'enabled': True, 'turn_host': 'turn.example.com', 'auth_secret': 'sek', 'turn_protocol': 'udp'})
    assert up.status_code == 200, up.json
    assert up.json['data']['has_secret'] is True and up.json['data']['turn_host'] == 'turn.example.com'
    # invalid protocol rejected
    assert client.put('/api/v1/portal/config', headers=h, json={'turn_protocol': 'sip'}).status_code == 400
    ice = client.get('/api/v1/portal/ice-servers', headers=h).json['data']['ice_servers']
    assert any('credential' in s for s in ice)
