"""Share-link CRUD + public viewer (PLAN P6 R1). Creating requires `share:create` and
camera scope; the public viewer authenticates with the share token only (no user).
"""
from datetime import datetime, timedelta

from server.exception import (
    InvalidParameterException,
    NoPermissionException,
    RowNotFoundException,
)
from server.model import UTC
from server.model.camera import Camera
from server.model.event import Event
from server.model.share_link import KIND_CLIP, KIND_EVENT, ShareLink
from server.service import feature_flag, share_link
from server.service.permission import PermissionService

_EVENT_PRE_MS = 15_000
_EVENT_POST_MS = 30_000


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard_flag():
    if not feature_flag.is_enabled('share_links'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    if not camera_uuid:
        raise InvalidParameterException('camera_uuid required')
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


class ShareLinkController:
    @classmethod
    def create(cls, user, data: dict) -> dict:
        _guard_flag()
        kind = data.get('kind') or KIND_CLIP

        if kind == KIND_EVENT:
            ev = Event.get_by_id(data.get('event_id'))
            if not ev:
                raise RowNotFoundException('event not found')
            camera = Camera.get_by_id(ev.camera_id)
            if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
                raise NoPermissionException('camera_scope_denied')
            start = ev.start_ts - timedelta(milliseconds=_EVENT_PRE_MS)
            end = (ev.end_ts or ev.start_ts) + timedelta(milliseconds=_EVENT_POST_MS)
            target_ref = str(ev.id)
            label = data.get('label') or ('%s · %s' % (camera.name, ev.type))
        elif kind == KIND_CLIP:
            camera = _scoped_camera(user, data.get('camera_uuid'))
            start = _parse_ms(data.get('range_start'))
            end = _parse_ms(data.get('range_end'))
            if start is None or end is None or end <= start:
                raise InvalidParameterException('valid range_start/range_end required')
            if (end - start) > timedelta(hours=6):
                raise InvalidParameterException('clip range too long (max 6h)')
            target_ref = None
            label = data.get('label')
        else:
            raise InvalidParameterException('invalid kind')

        link, token = share_link.create(
            kind=kind, camera=camera, target_ref=target_ref, range_start=start, range_end=end,
            label=label, password=data.get('password'), max_views=data.get('max_views'),
            watermark=bool(data.get('watermark')), expires_in_s=data.get('expires_in_s'),
            actor_id=user.id)
        out = link.to_dict()
        out['token'] = token                          # plaintext — shown once
        out['path'] = '/s/%s' % token
        return out

    @classmethod
    def list_links(cls, user) -> dict:
        _guard_flag()
        scope = None if PermissionService.is_superuser(user) else user.id
        return {'items': [s.to_dict() for s in ShareLink.list_for_user(scope)]}

    @classmethod
    def revoke(cls, user, share_id) -> dict:
        _guard_flag()
        link = ShareLink.get_by_id(share_id)
        if not link:
            raise RowNotFoundException()
        if link.created_by_id != user.id and not PermissionService.is_superuser(user):
            raise NoPermissionException('not_owner')
        link.revoke(actor_id=user.id)
        return link.to_dict()

    # ── public viewer (share-token only) ───────────────────────────────────────
    @classmethod
    def public_view(cls, token: str, password: str | None, ip: str | None) -> dict:
        link = share_link.resolve(token)
        if not link:
            raise RowNotFoundException('invalid_link')
        reason = link.status_reason()
        if reason:
            return {'status': reason}
        if link.password_hash is not None:
            if not share_link.rate_limit_ok(token, ip):
                raise NoPermissionException('rate_limited')
            if not share_link.verify_password(link, password):
                return {'status': 'password_required', 'has_password': True}

        link.register_view()
        camera = Camera.get_by_id(link.camera_id)
        payload = share_link.public_payload(link, camera)
        payload['status'] = 'ok'
        payload['segments'] = share_link.segments_for(link)
        return payload

    @classmethod
    def public_segment_path(cls, token: str, segment_id: int):
        """Return (segment, ok) for share-scoped media serving; raises on denial."""
        link = share_link.resolve(token)
        if not link or not link.is_live():
            raise NoPermissionException('link_unavailable')
        from server.model.segment import Segment
        seg = Segment.get_by_id(segment_id)
        if not share_link.authorize_segment(link, seg):
            raise NoPermissionException('segment_denied')
        return seg
