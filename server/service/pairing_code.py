"""Monitor pairing code (PLAN P5 §7.1, §11). CSPRNG 6-digit, sha256(code+pepper) stored
(never plaintext), 60s TTL, atomic one-time consume, per-IP global rate limit. Brute force
is bounded by 60s + 10^6 space + global rate limit (code-only lookup)."""
import hashlib
import secrets
from datetime import timedelta

import config
from server.model import utcnow
from server.model.monitor import STATUS_PENDING, Monitor
from server.model.pairing_code import PairingCode

CLAIM_RATE_PER_MIN = 10


def _hash(code: str) -> str:
    return hashlib.sha256((code + config.PAIRING_CODE_PEPPER).encode()).hexdigest()


def issue(monitor: Monitor, ip: str | None = None, actor_id=None) -> dict:
    PairingCode.expire_active_for_monitor(monitor.id)          # one active code at a time
    code = '%06d' % secrets.randbelow(1_000_000)
    expires = utcnow() + timedelta(seconds=config.PAIRING_CODE_TTL_S)
    PairingCode.create(monitor.id, _hash(code), expires, ip=ip, actor_id=actor_id)
    monitor.update(status=STATUS_PENDING)
    return {'code': code, 'expires_in': config.PAIRING_CODE_TTL_S, 'expires_at': expires}


def claim(code: str, ip: str | None = None, ua: str | None = None):
    """Returns (monitor, token_pair). Raises ValueError('invalid_or_expired') on any failure."""
    if not code or not code.isdigit() or len(code) != 6:
        raise ValueError('invalid_or_expired')
    row = PairingCode.find_active(_hash(code))
    if not row or row.attempts >= row.max_attempts:
        raise ValueError('invalid_or_expired')
    if not row.consume():                                      # atomic — concurrent claim loses
        raise ValueError('invalid_or_expired')
    monitor = Monitor.get_by_id(row.monitor_id)
    if not monitor or not monitor.enabled or monitor.deleted_at is not None:
        raise ValueError('invalid_or_expired')
    monitor.mark_paired(ip, ua)
    from server.model.dashboard import Dashboard
    from server.service.token import TokenService
    dash = Dashboard.get_by_id(monitor.dashboard_id)
    pair = TokenService.issue_monitor_pair(monitor, dash.uuid if dash else '')
    return monitor, pair


def rate_limit_ok(ip: str | None) -> bool:
    """Per-IP global claim rate limit (CLAIM_RATE_PER_MIN)."""
    from server.service.token import get_redis
    try:
        r = get_redis()
        key = '%s:pairclaim:%s' % (config.REDIS_KEY_PREFIX, ip or 'unknown')
        n = r.incr(key)
        if n == 1:
            r.expire(key, 60)
        return n <= CLAIM_RATE_PER_MIN
    except Exception:
        return True
