"""Signed short-lived tickets for the nginx→go2rtc WebSocket media proxy (PLAN P1 §6.3 /
P9 remote portal).

A browser can't attach a JWT to a WebSocket handshake the way `fetch()` does, and we don't
want live media bytes flowing through the (uWSGI, thread-per-request) Python app. So remote
low-latency playback works TURN-free like this:

  1. client POSTs /live/ws-ticket/<name>  → JWT + camera scope checked → gets a ticket
  2. client opens  ws(s)://<host>/live-ws/?src=<name>&ticket=<t>
  3. nginx auth_request → GET /live/ws-auth validates the ticket (HMAC + expiry + src bind)
  4. nginx upgrades and proxies to go2rtc /api/ws — MSE over WebSocket, no TURN needed

A ticket is `<exp>.<b64url(HMAC-SHA256(secret, "<name>\\n<exp>"))>`; it carries its own expiry
so verification is a stateless constant-time compare. The short TTL bounds replay, and the
HMAC binds the ticket to one stream name so it can't be reused for another camera.
"""
import base64
import hashlib
import hmac
import time

import config

DEFAULT_TTL = 30          # seconds — long enough to open a socket, short enough to bound replay
_MIN_TTL = 5


def _secret() -> bytes:
    base = config.SECRET_KEY or config.JWT_SECRET or 'dev-insecure'
    return hashlib.sha256((base + ':live-ws').encode()).digest()


def _sign(name: str, exp: int) -> str:
    mac = hmac.new(_secret(), ('%s\n%d' % (name, exp)).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip('=')


def issue(go2rtc_name: str, ttl: int = DEFAULT_TTL) -> dict:
    ttl = max(_MIN_TTL, int(ttl))
    exp = int(time.time()) + ttl
    return {'ticket': '%d.%s' % (exp, _sign(go2rtc_name, exp)), 'expires_in': ttl}


def verify(go2rtc_name: str, ticket: str) -> bool:
    if not go2rtc_name or not ticket or '.' not in ticket:
        return False
    exp_s, sig = ticket.split('.', 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(go2rtc_name, exp))
