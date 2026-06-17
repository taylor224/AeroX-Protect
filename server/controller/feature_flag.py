"""Feature-flag admin (PLAN P6 §5.5). Any authenticated user may READ the enabled map
(needed to gate UI); only `feature_flags:manage` (admin) may toggle.
"""
from server.exception import InvalidParameterException
from server.model.feature_flag import FEATURE_FLAG_SEEDS, HIDDEN_FLAG_KEYS
from server.service import feature_flag

_KNOWN = {k for k, _, _ in FEATURE_FLAG_SEEDS}


class FeatureFlagController:
    @classmethod
    def list_flags(cls) -> dict:
        # Hide always-on / config-driven / per-camera flags from the admin list; their
        # enabled state is still exposed via enabled_map() for the UI gates.
        items = [f for f in feature_flag.list_flags() if f.get('key') not in HIDDEN_FLAG_KEYS]
        return {'items': items, 'enabled': feature_flag.enabled_map()}

    @classmethod
    def set_flag(cls, key: str, data: dict, actor) -> dict:
        if key not in _KNOWN:
            raise InvalidParameterException('unknown flag')
        if 'enabled' not in data:
            raise InvalidParameterException('enabled required')
        return feature_flag.set_flag(
            key, bool(data['enabled']), value=data.get('value'), actor_id=actor.id)
