"""Recorder reconcile signal (PLAN P2 §5.4). API publishes; supervisor subscribes
(with a polling fallback so a lost message still converges)."""
import json
import logging

import config

logger = logging.getLogger(__name__)


def publish_reconcile(camera_id: int | None = None, action: str = 'reconcile'):
    from server.service.token import get_redis
    try:
        get_redis().publish(config.RECONCILE_CHANNEL,
                            json.dumps({'camera_id': str(camera_id) if camera_id else None, 'action': action}))
    except Exception as e:  # never let a signal failure break the request
        logger.warning('reconcile publish failed: %s', e)
