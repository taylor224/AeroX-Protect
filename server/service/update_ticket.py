"""Signed short-lived tickets for polling the native launcher's update-status API.

During a self-update the backend is stopped, so the browser cannot authenticate
its progress polls against the Flask app. Instead POST /system/update/apply mints
this HMAC ticket; the reverse proxy routes /updater/* straight to the launcher's
loopback control API, and the launcher — which knows SECRET_KEY from config\\axp.env —
verifies the ticket with nothing but stdlib hmac/hashlib (mirror the derivation
below when touching it: windows/launcher/axp_launcher/control.py).

Ticket = `<exp>.<b64url(HMAC-SHA256(sha256(SECRET_KEY + ':sys-update'), "update\\n<exp>"))>`
— same shape as server/service/live_ticket.py, bound to the fixed subject "update".
"""
import base64
import hashlib
import hmac
import time

import config

_SUBJECT = 'update'


def _secret() -> bytes:
    base = config.SECRET_KEY or config.JWT_SECRET or 'dev-insecure'
    return hashlib.sha256((base + ':sys-update').encode()).digest()


def _sign(exp: int) -> str:
    mac = hmac.new(_secret(), ('%s\n%d' % (_SUBJECT, exp)).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip('=')


def issue(ttl: int | None = None) -> dict:
    ttl = int(ttl or config.UPDATE_TICKET_TTL_S)
    exp = int(time.time()) + ttl
    return {'ticket': '%d.%s' % (exp, _sign(exp)), 'expires_in': ttl}


def verify(ticket: str) -> bool:
    if not ticket or '.' not in ticket:
        return False
    exp_s, sig = ticket.split('.', 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(exp))
