"""LPR read browsing + watchlist management (PLAN P7 A7). Reads are camera-scoped;
search spans the caller's allowed cameras (default-deny). Watchlist CRUD needs `lpr:manage`.
Flag-gated by `lpr`.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.camera import Camera
from server.model.plate_list import KINDS, KIND_DENY, PlateListEntry
from server.model.plate_read import PlateRead
from server.service import feature_flag, plate_normalize
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard():
    if not feature_flag.is_enabled('lpr'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _allowed_camera_ids(user) -> set[int] | None:
    """Camera ids the user may view (None = all). Default-deny for non-superusers."""
    if PermissionService.is_superuser(user):
        return None
    scope = PermissionService._merged_scope(user, 'camera_scope')
    star = scope.get('*')
    if star and ('view' in star or '*' in star):
        return None
    allowed: set[int] = set()
    for uuid, actions in scope.items():
        if uuid == '*':
            continue
        if 'view' in actions or '*' in actions:
            cam = Camera.get_by_uuid(uuid)
            if cam:
                allowed.add(cam.id)
    return allowed


class LprController:
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str, args) -> list[dict]:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        limit = min(safe_int(args.get('limit'), 50) or 50, 200)
        return [r.to_dict() for r in PlateRead.recent_for_camera(camera.id, limit)]

    @classmethod
    def search(cls, user, args) -> dict:
        _guard()
        allowed = _allowed_camera_ids(user)
        if allowed is not None and not allowed:
            return {'items': []}
        reads = PlateRead.search(
            camera_ids=(list(allowed) if allowed is not None else None),
            plate_key=plate_normalize.normalize(args.get('q')) or None,
            start=_parse_ms(args.get('start')), end=_parse_ms(args.get('end')),
            list_kind=(args.get('list_kind') or None),
            limit=min(safe_int(args.get('limit'), 100) or 100, 500))
        return {'items': [r.to_dict() for r in reads]}

    # ── watchlist ─────────────────────────────────────────────────────────────
    @classmethod
    def list_entries(cls, user, args) -> list[dict]:
        _guard()
        return [e.to_dict() for e in PlateListEntry.list_all(kind=(args.get('kind') or None))]

    @classmethod
    def create_entry(cls, user, data: dict) -> dict:
        _guard()
        plate_text = (data.get('plate_text') or '').strip()
        key = plate_normalize.match_key(plate_text)
        if not key:
            raise InvalidParameterException('plate_text required')
        kind = data.get('kind') or KIND_DENY
        if kind not in KINDS:
            raise InvalidParameterException('kind must be allow or deny')
        if PlateListEntry.match(key) is not None:
            raise InvalidParameterException('plate already in watchlist')
        e = PlateListEntry.create(plate_text=plate_text[:24], plate_key=key, kind=kind,
                                  label=data.get('label'), note=data.get('note'),
                                  action=data.get('action'), actor_id=user.id)
        return e.to_dict()

    @classmethod
    def update_entry(cls, user, entry_id, data: dict) -> dict:
        _guard()
        e = PlateListEntry.get_by_id(entry_id)
        if not e:
            raise RowNotFoundException()
        return e.modify(data, actor_id=user.id).to_dict()

    @classmethod
    def delete_entry(cls, user, entry_id):
        _guard()
        e = PlateListEntry.get_by_id(entry_id)
        if not e:
            raise RowNotFoundException()
        e.soft_delete(actor_id=user.id)
