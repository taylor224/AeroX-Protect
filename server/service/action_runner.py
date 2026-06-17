"""Action orchestration (PLAN P5 §5.4). Resolve each action's target + driver, run it with a
timeout, collect a uniform result dict. Drivers are imported lazily (heavy/optional deps)."""
import logging

logger = logging.getLogger(__name__)


def run_all(rule, trig) -> list[dict]:
    results = []
    for a in (rule.actions or []):
        try:
            res = run(a, trig)
        except Exception as exc:                       # noqa: BLE001 — record, keep going
            logger.exception('action failed')
            res = {'status': 'failed', 'error': str(exc)[:200]}
        res = {**res, 'target_id': a.get('target_id'), 'type': a.get('type')}
        results.append(res)
        if res.get('status') != 'success' and not a.get('continue_on_error', True):
            break
    return results


def run(action: dict, trig) -> dict:
    atype = action.get('type')
    params = action.get('params') or {}

    if atype == 'webhook':
        from server.driver import webhook as webhook_drv
        # inline config (per-automation) takes precedence over a pre-registered endpoint
        if params.get('url'):
            return webhook_drv.deliver_inline(params, event_payload(trig))
        from server.model.webhook_endpoint import WebhookEndpoint
        ep = WebhookEndpoint.get_by_id(action['target_id']) if action.get('target_id') else None
        if not ep or not ep.enabled:
            return {'status': 'failed', 'error': 'no_webhook'}
        return webhook_drv.deliver(ep, event_payload(trig))

    if atype in ('camera_enable', 'camera_disable'):
        return _set_camera_enabled(action, trig, enable=(atype == 'camera_enable'))

    if atype == 'sms':
        from server.driver import sms as sms_drv
        from server.service import feature_flag
        if not feature_flag.is_enabled('sms_notifications'):
            return {'status': 'skipped', 'error': 'sms_disabled'}
        to = params.get('to')
        if not to:
            return {'status': 'failed', 'error': 'no_recipient'}
        return sms_drv.send_event_to(to, event_payload(trig))

    if atype == 'email':
        from server.driver import email as email_drv
        # inline recipient (per-automation) — falls back to a pre-registered target for back-compat
        to = params.get('to')
        if to:
            return email_drv.send_event_to(to, event_payload(trig))
        from server.model.action_target import ActionTarget
        tgt = ActionTarget.get_by_id(action['target_id']) if action.get('target_id') else None
        if not tgt or not tgt.enabled:
            return {'status': 'failed', 'error': 'no_recipient'}
        return email_drv.send_event(tgt, event_payload(trig))

    if atype in ('speaker', 'io'):     # device targets (back-compat; configured outside the wizard)
        from server.model.action_target import ActionTarget
        tgt = ActionTarget.get_by_id(action['target_id']) if action.get('target_id') else None
        if not tgt or not tgt.enabled:
            return {'status': 'failed', 'error': 'no_target'}
        if atype == 'speaker':
            from server.driver import speaker
            return speaker.run(tgt, params)
        from server.driver import io as io_drv
        return io_drv.run(tgt, params)

    if atype == 'push':
        from server.service import notification_router
        return notification_router.push_for_trigger(trig, params)

    return {'status': 'failed', 'error': 'unknown_action_type'}


def _set_camera_enabled(action: dict, trig, enable: bool) -> dict:
    """Enable/disable a camera (params.camera_id, else the trigger's camera) + reconcile recording."""
    from server.model.camera import Camera
    from server.service.reconcile import publish_reconcile
    params = action.get('params') or {}
    cam_id = params.get('camera_id') or trig.camera_id
    if not cam_id:
        return {'status': 'failed', 'error': 'no_camera'}
    cam = Camera.get_by_id(int(cam_id))
    if not cam:
        return {'status': 'failed', 'error': 'no_camera'}
    cam.is_enabled = enable
    from server.model import db
    db.session.add(cam)
    db.session.commit()
    try:
        publish_reconcile(cam.id, 'enable_change')
    except Exception:
        pass
    return {'status': 'success', 'camera_id': str(cam.id), 'enabled': enable}


def event_payload(trig) -> dict:
    """Canonical payload shared by webhook/email/push."""
    out = {
        'type': trig.type or trig.trigger_type,
        'trigger_type': trig.trigger_type,
        'camera_id': str(trig.camera_id) if trig.camera_id else None,
        'event_id': str(trig.event_id) if trig.event_id else None,
        'subtype': trig.subtype, 'score': trig.score, 'ts': trig.ts,
        'classes': trig.classes, 'region': trig.region,
    }
    if trig.identity_id or trig.identity_name:
        out['identity_id'] = str(trig.identity_id) if trig.identity_id else None
        out['identity'] = trig.identity_name
    if getattr(trig, 'context', None):
        out['context'] = trig.context
    return out
