"""Opaque external API token verification (PLAN P5 §5.6). sha256(token+pepper) → DB lookup
→ revoked/expired check → per-token Redis rate limit. Camera scope intersection on responses."""
import config
from server.model.api_token import ApiToken, hash_token


def verify(raw: str | None) -> ApiToken | None:
    if not raw:
        return None
    tok = ApiToken.get_by_hash(hash_token(raw))
    if not tok or not tok.is_valid():
        return None
    return tok


def check_rate_limit(tok: ApiToken) -> bool:
    from server.service.token import get_redis
    try:
        r = get_redis()
        key = '%s:apitok:%s:rl' % (config.REDIS_KEY_PREFIX, tok.id)
        n = r.incr(key)
        if n == 1:
            r.expire(key, 60)
        return n <= (tok.rate_limit_per_min or 120)
    except Exception:
        return True


def allowed_camera_ids(tok: ApiToken) -> set[int] | None:
    """Token's camera scope (None = all)."""
    if not tok.camera_ids:
        return None
    out = set()
    for c in tok.camera_ids:
        try:
            out.add(int(c))
        except (TypeError, ValueError):
            pass
    return out
