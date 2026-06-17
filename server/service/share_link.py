"""Share-link service (PLAN P6 R1, §13). Issues opaque tokens, resolves them for the
public viewer, and authorizes share-scoped media. The token grants ONLY its clip/event —
segment serving is checked against the link's camera + time window. Password attempts are
rate-limited per token+IP (brute-force guard).
"""
import hmac

import config
from server.model.share_link import (
    KIND_EVENT,
    KINDS,
    ShareLink,
    hash_password,
    hash_token,
)
from server.service import playback_planner
from server.service.token import get_redis

DEFAULT_EXPIRY_S = 7 * 24 * 3600
MAX_EXPIRY_S = 30 * 24 * 3600
_PW_ATTEMPT_LIMIT = 10           # per token+ip per window
_PW_WINDOW_S = 300


def create(*, kind: str, camera, target_ref=None, range_start=None, range_end=None,
           label=None, password=None, max_views=None, watermark=False,
           expires_in_s=None, actor_id=None) -> tuple[ShareLink, str]:
    if kind not in KINDS:
        raise ValueError('invalid kind')
    ttl = DEFAULT_EXPIRY_S if not expires_in_s else min(int(expires_in_s), MAX_EXPIRY_S)
    token = ShareLink.new_token()
    link = ShareLink.create(
        kind=kind, camera_id=camera.id, token_hash=hash_token(token),
        target_ref=str(target_ref) if target_ref is not None else None,
        range_start=range_start, range_end=range_end, label=label,
        password_hash=hash_password(password) if password else None,
        watermark=bool(watermark),
        max_views=int(max_views) if max_views else None,
        expires_at=ShareLink.default_expiry(ttl), actor_id=actor_id)
    return link, token


def resolve(token: str) -> ShareLink | None:
    if not token:
        return None
    return ShareLink.get_by_hash(hash_token(token))


def verify_password(link: ShareLink, password: str | None) -> bool:
    if link.password_hash is None:
        return True
    if not password:
        return False
    return hmac.compare_digest(hash_password(password), link.password_hash)


def rate_limit_ok(token: str, ip: str | None) -> bool:
    """True if under the password-attempt limit for this token+ip window."""
    key = '%s:share_pw:%s:%s' % (config.REDIS_KEY_PREFIX, hash_token(token or '')[:16], ip or '-')
    try:
        r = get_redis()
        n = r.incr(key)
        if n == 1:
            r.expire(key, _PW_WINDOW_S)
        return n <= _PW_ATTEMPT_LIMIT
    except Exception:
        return True            # never let a redis hiccup lock out legitimate viewers


def segments_for(link: ShareLink) -> list[dict]:
    if link.range_start is None or link.range_end is None:
        return []
    return playback_planner.get_segments(link.camera_id, link.range_start, link.range_end)


def authorize_segment(link: ShareLink, segment) -> bool:
    """A segment is share-served only if it belongs to the link's camera and overlaps its
    window — the token cannot reach any other footage."""
    if segment is None or segment.camera_id != link.camera_id:
        return False
    if link.range_start is None or link.range_end is None:
        return False
    return segment.start_ts <= link.range_end and (segment.end_ts or segment.start_ts) >= link.range_start


def public_payload(link: ShareLink, camera) -> dict:
    """Non-sensitive metadata for the public viewer (no token/hash)."""
    from server.model import to_epoch_ms
    return {
        'kind': link.kind,
        'label': link.label,
        'camera_name': camera.name if camera else None,
        'range_start': to_epoch_ms(link.range_start),
        'range_end': to_epoch_ms(link.range_end),
        'watermark': bool(link.watermark),
        'is_event': link.kind == KIND_EVENT,
        'target_ref': link.target_ref,
    }
