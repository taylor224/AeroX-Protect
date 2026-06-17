"""Feature-flag resolution (PLAN P6 §5.5, §13). `is_enabled()` is the single gate used
by P6 API entry points and the frontend flag map. A short per-process TTL cache keeps the
gate cheap (flags change rarely); writes invalidate it locally. Cross-process staleness is
bounded by the TTL — acceptable for low-churn toggles.
"""
import time

from server.model.feature_flag import FeatureFlag

_CACHE_TTL_S = 15.0
_cache: dict[str, bool] = {}
_cache_at: float = 0.0


def _now() -> float:
    return time.monotonic()


def _refresh() -> dict[str, bool]:
    global _cache, _cache_at
    _cache = {f.key: bool(f.enabled) for f in FeatureFlag.list_all()}
    _cache_at = _now()
    return _cache


def invalidate():
    global _cache_at
    _cache_at = 0.0


def _map() -> dict[str, bool]:
    if _now() - _cache_at > _CACHE_TTL_S:
        return _refresh()
    return _cache


def is_enabled(key: str, *, default: bool = False) -> bool:
    """True if the flag exists and is enabled. Unknown keys → ``default``."""
    return _map().get(key, default)


def enabled_map() -> dict[str, bool]:
    """{key: enabled} for the frontend to gate UI in one fetch."""
    return dict(_map())


def list_flags() -> list[dict]:
    return [f.to_dict() for f in FeatureFlag.list_all()]


def set_flag(key: str, enabled: bool, *, value=None, actor_id=None) -> dict:
    row = FeatureFlag.set_enabled(key, enabled, value=value, actor_id=actor_id)
    invalidate()
    return row.to_dict()
