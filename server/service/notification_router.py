"""Web-push dispatch for flow `push` action nodes. The P5 subscription-based
notification router was retired with the rule engine — flows are now the only
notification policy, and they target registered browser push subscriptions directly."""
import logging

logger = logging.getLogger(__name__)


def push_for_trigger(trig, params: dict) -> dict:
    """Flow push action — web-push to params.user_ids' registered browsers, or every
    registered browser when no users are specified. Custom title/message from the
    flow override the default event-derived text."""
    from server.driver import push as push_drv
    from server.model.push_subscription import PushSubscription

    data = {
        'title': params.get('title') or '%s 감지' % (trig.subtype or trig.type or 'event'),
        'body': params.get('message') or trig.subtype or '',
        'priority': 'high',
        'deeplink': '/events/%s' % trig.event_id if trig.event_id else '/events',
    }
    user_ids = params.get('user_ids')
    if user_ids:
        subs = [s for uid in user_ids for s in PushSubscription.active_for_user(int(uid))]
    else:
        subs = PushSubscription.active_all()
    sent = 0
    for s in subs:
        try:
            if push_drv.send(s, data).get('status') == 'success':
                sent += 1
        except Exception:                       # noqa: BLE001 — one dead endpoint ≠ fail all
            logger.exception('push dispatch failed (sub %s)', s.id)
    return {'status': 'success' if sent else 'skipped', 'pushed': sent}
