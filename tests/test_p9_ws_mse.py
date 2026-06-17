"""P9 — TURN-free low-latency live via the nginx→go2rtc MSE WebSocket.

Media bytes never touch the Python app: the backend only issues/validates a short-lived
HMAC ticket that nginx checks (auth_request) before upgrading the socket to go2rtc. Tested:
ticket sign/verify (name binding, expiry, tamper), the scope-checked issue endpoint, and the
auth_request endpoint (200 on a valid ticket, 403 otherwise).
"""
from tests.conftest import login


# ── ticket sign/verify ───────────────────────────────────────────────────────
def test_ticket_roundtrip_and_binding():
    from server.service import live_ticket
    t = live_ticket.issue('camera_main')['ticket']
    assert live_ticket.verify('camera_main', t)
    assert not live_ticket.verify('other_stream', t)        # bound to one stream name


def test_ticket_expiry():
    from server.service import live_ticket
    t = live_ticket.issue('s', ttl=5)['ticket']
    assert live_ticket.verify('s', t)
    exp, sig = t.split('.', 1)
    stale = '%d.%s' % (int(exp) - 10, sig)                  # force the expiry into the past
    assert not live_ticket.verify('s', stale)


def test_ticket_tamper_and_garbage():
    from server.service import live_ticket
    t = live_ticket.issue('s')['ticket']
    exp, sig = t.split('.', 1)
    assert not live_ticket.verify('s', '%s.%sX' % (exp, sig[:-1]))   # bad signature
    assert not live_ticket.verify('s', 'not-a-ticket')
    assert not live_ticket.verify('s', '')
    assert not live_ticket.verify('', t)


# ── endpoints ────────────────────────────────────────────────────────────────
def _camera_stream(client, h) -> str:
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'WS', 'host': '192.0.2.231', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']
    return cam['streams'][0]['go2rtc_name']


def test_ws_ticket_requires_auth(client, mock_go2rtc):
    h = login(client)
    name = _camera_stream(client, h)
    assert client.post('/api/v1/live/ws-ticket/%s' % name).status_code in (401, 403)   # no token
    r = client.post('/api/v1/live/ws-ticket/%s' % name, headers=h)
    assert r.status_code == 200, r.json
    assert r.json['data']['ticket'] and r.json['data']['expires_in'] >= 5


def test_ws_auth_validates_ticket(client, mock_go2rtc):
    h = login(client)
    name = _camera_stream(client, h)
    ticket = client.post('/api/v1/live/ws-ticket/%s' % name, headers=h).json['data']['ticket']
    # nginx passes name+ticket as headers → 200
    assert client.get('/api/v1/live/ws-auth',
                      headers={'X-Live-Src': name, 'X-Live-Ticket': ticket}).status_code == 200
    # query-arg form also accepted
    assert client.get('/api/v1/live/ws-auth?src=%s&ticket=%s' % (name, ticket)).status_code == 200
    # X-Original-URI form (how nginx auth_request forwards the original request line) → 200
    assert client.get('/api/v1/live/ws-auth',
                      headers={'X-Original-URI': '/live-ws/?src=%s&ticket=%s' % (name, ticket)}).status_code == 200
    # wrong stream / missing → 403
    assert client.get('/api/v1/live/ws-auth',
                      headers={'X-Live-Src': 'nope', 'X-Live-Ticket': ticket}).status_code == 403
    assert client.get('/api/v1/live/ws-auth').status_code == 403
