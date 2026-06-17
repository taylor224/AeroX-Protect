"""Web-push (VAPID) driver (PLAN P5 §7.3). pywebpush is imported lazily (optional dep); 410/404
disables the subscription. Tests monkeypatch `_webpush`."""
import json
import logging

import config

logger = logging.getLogger(__name__)


def _webpush(subscription_info, data, ttl):
    from pywebpush import webpush
    return webpush(
        subscription_info=subscription_info, data=data,
        vapid_private_key=config.VAPID_PRIVATE_KEY,
        vapid_claims={'sub': config.VAPID_SUBJECT}, ttl=ttl)


def send(subscription, data: dict, ttl: int = 60) -> dict:
    if not config.VAPID_PRIVATE_KEY:
        return {'status': 'skipped', 'error': 'vapid_not_configured'}
    info = {'endpoint': subscription.endpoint, 'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth}}
    try:
        _webpush(info, json.dumps(data), ttl)
        subscription.mark_success()
        return {'status': 'success'}
    except Exception as exc:                       # noqa: BLE001
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
        if code in (404, 410):
            subscription.disable()                 # Gone → drop subscription
            return {'status': 'failed', 'error': 'gone'}
        logger.warning('webpush failed: %s', exc)
        return {'status': 'failed', 'error': str(exc)[:200]}
