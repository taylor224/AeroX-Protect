from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.camera import Camera
from server.model.event import Event
from server.model.recording import CLASS_PROTECTED, Recording
from server.service import event_pipeline, playback_planner
from server.service.permission import PermissionService


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _allowed_camera_ids(user) -> set[int] | None:
    """Camera ids the user may view (None = all). Default-deny for non-superusers."""
    if PermissionService.is_superuser(user):
        return None
    scope = PermissionService._merged_scope(user, 'camera_scope')
    star = scope.get('*')
    if star and ('view' in star or '*' in star):
        return None
    allowed = set()
    for uuid, actions in scope.items():
        if uuid == '*':
            continue
        if 'view' in actions or '*' in actions:
            try:
                allowed.add(Camera.get_by_uuid(uuid).id)
            except RowNotFoundException:
                pass
    return allowed


class EventController:
    @classmethod
    def list_events(cls, user, args) -> dict:
        allowed = _allowed_camera_ids(user)
        requested = [int(c) for c in args.getlist('camera_id') if c.isdigit()] if hasattr(args, 'getlist') else []
        if allowed is not None:
            camera_ids = list(set(requested) & allowed) if requested else list(allowed)
            if not camera_ids:
                return {'count': 0, 'items': []}
        else:
            camera_ids = requested or None

        types = args.getlist('type') if hasattr(args, 'getlist') else None
        from server.util.tool import safe_int
        total, rows = Event.get_list(
            camera_ids=camera_ids, types=types or None, subtype=args.get('subtype'),
            start=_parse_ms(args.get('start')), end=_parse_ms(args.get('end')),
            min_score=safe_int(args.get('min_score'), None) if args.get('min_score') else None,
            has_recording={'true': True, 'false': False}.get((args.get('has_recording') or '').lower()),
            state=safe_int(args.get('state'), None) if args.get('state') else None,
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 20))),
            sort='start_ts', order=(args.get('order') or 'desc'))
        return {'count': total, 'items': [e.to_dict() for e in rows]}

    @classmethod
    def get_event(cls, user, event_id: int) -> dict:
        ev = cls._scoped_event(user, event_id)
        return ev.to_dict(with_raw=PermissionService.is_superuser(user))

    @classmethod
    def timeline(cls, user, camera_uuid: str, start, end, types) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        markers = [
            {'ts': e.to_dict()['start_ts'], 'type': e.type, 'count': 1,
             'top_score': e.score, 'event_id': str(e.id),
             # lets the client snap timeline clicks to playable event clips (vs notify-only
             # noise like video_loss, which has no recording)
             'recording_id': str(e.recording_id) if e.recording_id else None}
            for e in Event.get_markers(camera.id, start, end, types)
        ]
        coverage = playback_planner.build_timeline(camera.id, start, end)['ranges']
        return {'markers': markers, 'coverage': coverage}

    @classmethod
    def overlay(cls, user, event_id: int) -> dict:
        ev = cls._scoped_event(user, event_id)
        region = ev.region or {}
        return {'shapes': region.get('shapes', []), 'w': region.get('w', 1), 'h': region.get('h', 1),
                'ts_offset_ms': 0}

    @classmethod
    def save_event(cls, user, event_id: int, data: dict) -> dict:
        ev = cls._scoped_event(user, event_id)
        if ev.recording_id:
            rec = Recording.get_by_id(ev.recording_id)
            if rec:
                rec.retention_class = data.get('retention_class') or CLASS_PROTECTED
                from server.model import db
                db.session.add(rec)
                db.session.commit()
        return ev.to_dict()

    @classmethod
    def delete_event(cls, user, event_id: int):
        cls._scoped_event(user, event_id).soft_delete()

    @classmethod
    def simulate(cls, user, camera_uuid: str, raw: dict) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        if not raw.get('type'):
            raise InvalidParameterException('type required')
        ev = event_pipeline.handle(camera, raw, 'manual')
        if ev is None:
            raise InvalidParameterException('event ignored (unknown type)')
        # re-read for recording_id set by inline materialize
        fresh = Event.get_by_id(ev.id)
        return fresh.to_dict() if fresh else ev.to_dict()

    @classmethod
    def _scoped_event(cls, user, event_id: int) -> Event:
        ev = Event.get_by_id(event_id)
        if not ev:
            raise RowNotFoundException()
        camera = Camera.get_by_id(ev.camera_id)
        if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        return ev
