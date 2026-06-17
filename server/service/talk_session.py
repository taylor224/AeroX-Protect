"""Two-way audio talk sessions (PLAN P6 L1). A camera has at most ONE active speaker —
a Redis lock (`axp:talk:{camera_id}`) enforces it. The lock auto-expires (TTL) so a
dropped client never wedges the backchannel; the same speaker re-offering refreshes it.
"""
import config
from server.service.token import get_redis

TTL_S = 120


def _key(camera_id) -> str:
    return '%s:talk:%s' % (config.REDIS_KEY_PREFIX, camera_id)


def acquire(camera_id, user_id, ttl: int = TTL_S) -> bool:
    """True if this user holds the (single) talk lock — fresh acquire or refresh."""
    r = get_redis()
    key = _key(camera_id)
    if r.set(key, str(user_id), nx=True, ex=ttl):
        return True
    if r.get(key) == str(user_id):       # same speaker → extend
        r.expire(key, ttl)
        return True
    return False


def release(camera_id, user_id) -> bool:
    r = get_redis()
    key = _key(camera_id)
    if r.get(key) == str(user_id):
        r.delete(key)
        return True
    return False


def current_speaker(camera_id):
    return get_redis().get(_key(camera_id))
