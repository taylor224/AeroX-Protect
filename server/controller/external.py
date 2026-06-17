"""External API (audience=api opaque token) controller (PLAN P5 §5.3, §7.6). Scope + camera
intersection enforced; viewer DTOs only (no credentials/host)."""
import secrets
from datetime import datetime

from server.exception import InvalidParameterException, RowNotFoundException
from server.model import UTC, to_epoch_ms, utcnow
from server.model.camera import Camera
from server.model.event import Event
from server.model.webhook_endpoint import PURPOSE_SUBSCRIPTION, WebhookEndpoint
from server.service import api_token as api_token_svc
from server.util.tool import safe_int


def _parse_ms(value):
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _scoped_camera_ids(token, requested):
    allowed = api_token_svc.allowed_camera_ids(token)
    if allowed is None:
        return requested or None
    return list(set(requested) & allowed) if requested else list(allowed)


class ExternalController:
    @classmethod
    def list_events(cls, token, args) -> dict:
        requested = [int(c) for c in args.getlist('camera_id') if c.isdigit()] if hasattr(args, 'getlist') else []
        camera_ids = _scoped_camera_ids(token, requested)
        if api_token_svc.allowed_camera_ids(token) is not None and not camera_ids:
            return {'count': 0, 'items': []}
        types = args.getlist('type') if hasattr(args, 'getlist') else None
        total, rows = Event.get_list(
            camera_ids=camera_ids, types=types or None,
            start=_parse_ms(args.get('from')), end=_parse_ms(args.get('to')),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [e.to_dict() for e in rows]}

    @classmethod
    def get_event(cls, token, event_id: int) -> dict:
        ev = Event.get_by_id(event_id)
        if not ev:
            raise RowNotFoundException()
        allowed = api_token_svc.allowed_camera_ids(token)
        if allowed is not None and ev.camera_id not in allowed:
            raise RowNotFoundException()
        return ev.to_dict()

    @classmethod
    def state(cls, token) -> dict:
        import config
        allowed = api_token_svc.allowed_camera_ids(token)
        cams = []
        for c in Camera.get_all_enabled():
            if allowed is not None and c.id not in allowed:
                continue
            cams.append({'uuid': c.uuid, 'name': c.name, 'online': c.status == 'online',
                         'status': c.status})
        return {
            'cameras': cams,
            'system': {'version': getattr(config, 'APP_VERSION', '5'), 'server_time': to_epoch_ms(utcnow())},
        }

    @classmethod
    def create_subscription(cls, token, data: dict) -> dict:
        if not data.get('url'):
            raise InvalidParameterException('url required')
        # clamp the subscription's camera filter to the token's own camera scope —
        # otherwise a camera-scoped token could subscribe to out-of-scope cameras' events
        allowed = api_token_svc.allowed_camera_ids(token)
        requested = data.get('camera_ids')
        if allowed is not None:
            req_set = {int(c) for c in requested if str(c).lstrip('-').isdigit()} if requested else None
            scoped_ids = sorted(req_set & allowed) if req_set else sorted(allowed)
            if not scoped_ids:
                raise InvalidParameterException('camera_ids outside token scope')
        else:
            scoped_ids = requested
        secret = data.get('secret') or secrets.token_urlsafe(24)
        hook = WebhookEndpoint.create({
            'name': data.get('name') or ('ext-%s' % token.token_prefix),
            'url': data['url'], 'secret': secret, 'purpose': PURPOSE_SUBSCRIPTION,
            'subscription_filter': {'event_types': data.get('event_types'), 'camera_ids': scoped_ids},
            'api_token_id': token.id,
        })
        return {**hook.to_dict(), 'secret': secret}      # secret returned once

    @classmethod
    def delete_subscription(cls, token, hook_uuid: str):
        hook = WebhookEndpoint.get_by_uuid(hook_uuid)
        if not hook or str(hook.api_token_id) != str(token.id):
            raise RowNotFoundException()
        hook.soft_delete()

    @classmethod
    def deliver_subscriptions(cls, event_payload: dict):
        """Fan-out an event to active external webhook subscriptions (filtered)."""
        from server.driver import webhook as webhook_drv
        from server.model.api_token import ApiToken
        cam_id = event_payload.get('camera_id')
        for hook in WebhookEndpoint.active_subscriptions():
            flt = hook.subscription_filter or {}
            if flt.get('event_types') and event_payload.get('type') not in flt['event_types']:
                continue
            if flt.get('camera_ids') and str(cam_id) not in [str(c) for c in flt['camera_ids']]:
                continue
            # defense-in-depth: re-check the owning token's CURRENT camera scope so a
            # later-narrowed (or revoked) token stops leaking events it no longer covers
            if hook.api_token_id is not None:
                tok = ApiToken.get_by_id(hook.api_token_id)
                if tok is None or not tok.is_valid():
                    continue
                allowed = api_token_svc.allowed_camera_ids(tok)
                if allowed is not None and cam_id is not None:
                    try:
                        if int(cam_id) not in allowed:
                            continue
                    except (TypeError, ValueError):
                        continue
            webhook_drv.deliver(hook, event_payload)
