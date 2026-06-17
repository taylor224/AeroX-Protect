"""Notification routing (PLAN P5 §7.4). Event/rule firing → matching subscriptions →
in-app row (always, for the notification center) + external channels (push/email/webhook),
honoring mute/snooze, priority floor, and quiet hours (KST). Batching is simplified to
immediate dispatch in MVP (Redis ZSET batch flush is a follow-up)."""
import logging

from server.model import to_epoch_ms, utcnow
from server.model.notification import Notification
from server.model.notification_subscription import (
    CHANNEL_EMAIL,
    CHANNEL_PUSH,
    CHANNEL_SMS,
    CHANNEL_WEBHOOK,
    PRIORITY_RANK,
    NotificationSubscription,
)
from server.service import rule_evaluator

logger = logging.getLogger(__name__)
CRITICAL_SUBTYPES = {'intrusion', 'tamper'}


def priority_for(payload: dict) -> str:
    t, sub = payload.get('type'), payload.get('subtype')
    if t in CRITICAL_SUBTYPES or sub in CRITICAL_SUBTYPES:
        return 'critical'
    if t in ('object', 'line_crossing', 'intrusion'):
        return 'high'
    return 'normal'


def route_event(payload: dict) -> dict:
    """payload = P3 event_outbox payload (event.to_dict). Returns per-channel counts."""
    priority = priority_for(payload)
    counts = {'inapp': 0, 'push': 0, 'email': 0, 'webhook': 0, 'sms': 0}
    inapp_users = set()
    for sub in NotificationSubscription.active_all():
        if not _matches(sub, payload) or _suppressed(sub, priority, payload):
            continue
        if sub.user_id not in inapp_users:
            _create_inapp(sub.user_id, payload, priority)
            counts['inapp'] += 1
            inapp_users.add(sub.user_id)
        if sub.channel == CHANNEL_PUSH:
            counts['push'] += _dispatch_push(sub.user_id, payload, priority)
        elif sub.channel == CHANNEL_EMAIL:
            counts['email'] += _dispatch_email(sub.user_id, payload)
        elif sub.channel == CHANNEL_WEBHOOK and sub.webhook_endpoint_id:
            counts['webhook'] += _dispatch_webhook(sub.webhook_endpoint_id, payload)
        elif sub.channel == CHANNEL_SMS:
            counts['sms'] += _dispatch_sms(sub, payload)
    return counts


def push_for_trigger(trig, params: dict) -> dict:
    """Rule push action — push to params.user_ids (or all push subscribers). Custom
    title/message from the automation override the default event-derived text."""
    payload = {'type': trig.type or trig.trigger_type, 'camera_id': str(trig.camera_id) if trig.camera_id else None,
               'event_id': str(trig.event_id) if trig.event_id else None, 'subtype': trig.subtype, 'ts': trig.ts}
    if params.get('title'):
        payload['title'] = params['title']
    if params.get('message'):
        payload['message'] = params['message']
    user_ids = params.get('user_ids')
    sent = 0
    if user_ids:
        for uid in user_ids:
            sent += _dispatch_push(int(uid), payload, 'high')
    else:
        for sub in NotificationSubscription.active_all():
            if sub.channel == CHANNEL_PUSH:
                sent += _dispatch_push(sub.user_id, payload, 'high')
    return {'status': 'success' if sent else 'skipped', 'pushed': sent}


# ── matching / suppression ──────────────────────────────────────────────────────
def _matches(sub, p: dict) -> bool:
    if sub.event_types and p.get('type') not in sub.event_types:
        return False
    if sub.camera_ids and str(p.get('camera_id')) not in [str(c) for c in sub.camera_ids]:
        return False
    if sub.object_classes and p.get('type') == 'object' and p.get('subtype') not in sub.object_classes:
        return False
    return True


def _suppressed(sub, priority: str, payload: dict) -> bool:
    if sub.muted:
        return True
    if sub.muted_until and utcnow() < sub.muted_until:
        return True
    if PRIORITY_RANK.get(priority, 1) < PRIORITY_RANK.get(sub.min_priority, 1):
        return True
    # event payloads carry 'start_ts' (epoch ms), rule triggers carry 'ts';
    # fall back to delivery time — a None ts would count as "always quiet".
    ts_ms = payload.get('ts') or payload.get('start_ts') or to_epoch_ms(utcnow())
    if sub.quiet_hours and rule_evaluator.in_quiet(ts_ms, sub.quiet_hours):
        if not ((sub.quiet_hours or {}).get('allow_critical') and priority == 'critical'):
            return True
    return False


# ── delivery ────────────────────────────────────────────────────────────────────
def _create_inapp(user_id: int, payload: dict, priority: str):
    cam = payload.get('camera_id')
    title = '%s 감지' % (payload.get('subtype') or payload.get('type') or 'event')
    Notification.create(
        user_id=user_id, event_id=int(payload['id']) if payload.get('id') else None,
        camera_id=int(cam) if cam else None, type='event', priority=priority, title=title,
        body=payload.get('subtype'), snapshot_path=payload.get('snapshot_path'),
        deeplink='/events/%s' % payload['id'] if payload.get('id') else None,
        channels_sent={'inapp': 'sent'})


def _dispatch_push(user_id: int, payload: dict, priority: str) -> int:
    try:
        from server.driver import push as push_drv
        from server.model.push_subscription import PushSubscription
        subs = PushSubscription.active_for_user(user_id)
        data = {'title': payload.get('title') or '%s 감지' % (payload.get('subtype') or payload.get('type') or 'event'),
                'body': payload.get('message') or payload.get('subtype') or '', 'priority': priority,
                'deeplink': '/events/%s' % payload['event_id'] if payload.get('event_id') else '/events'}
        return sum(1 for s in subs if push_drv.send(s, data).get('status') == 'success')
    except Exception:
        logger.exception('push dispatch failed')
        return 0


def _dispatch_email(user_id: int, payload: dict) -> int:
    try:
        from server.driver import email as email_drv
        from server.model.user import User
        user = User.get_by_id(user_id)
        if not user or not user.email:
            return 0
        return 1 if email_drv.send_event_to(user.email, payload).get('status') == 'success' else 0
    except Exception:
        logger.exception('email dispatch failed')
        return 0


def _dispatch_sms(sub, payload: dict) -> int:
    try:
        from server.service import feature_flag
        if not feature_flag.is_enabled('sms_notifications'):
            return 0
        from server.driver import sms as sms_drv
        return 1 if sms_drv.send_event_to(sub.sms_to, payload).get('status') == 'success' else 0
    except Exception:
        logger.exception('sms dispatch failed')
        return 0


def _dispatch_webhook(endpoint_id: int, payload: dict) -> int:
    try:
        from server.driver import webhook as webhook_drv
        from server.model.webhook_endpoint import WebhookEndpoint
        ep = WebhookEndpoint.get_by_id(endpoint_id)
        if not ep or not ep.enabled:
            return 0
        return 1 if webhook_drv.deliver(ep, payload).get('status') == 'success' else 0
    except Exception:
        logger.exception('webhook dispatch failed')
        return 0
