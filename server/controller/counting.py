"""Counting lines CRUD + analytics (PLAN P6 A2/A3). Camera-scoped; flag-gated by
`object_counting`/`loitering`. Lines/regions feed `service/counting.py` from detection ingest.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.camera import Camera
from server.model.counting import KIND_LINE, KINDS, CountingLine, CountingStat
from server.service import feature_flag
from server.service.permission import PermissionService


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard():
    if not (feature_flag.is_enabled('object_counting') or feature_flag.is_enabled('loitering')):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _validate(data: dict):
    kind = data.get('kind') or KIND_LINE
    if kind not in KINDS:
        raise InvalidParameterException('kind must be line or region')
    geom = data.get('geometry')
    if not isinstance(geom, list):
        raise InvalidParameterException('geometry required')
    if kind == KIND_LINE and len(geom) != 2:
        raise InvalidParameterException('line geometry needs exactly 2 points')
    if kind != KIND_LINE and len(geom) < 3:
        raise InvalidParameterException('region geometry needs ≥3 points')
    if not data.get('name'):
        raise InvalidParameterException('name required')


def _require(user, line_id) -> CountingLine:
    line = CountingLine.get_by_id(line_id)
    if not line:
        raise RowNotFoundException()
    camera = Camera.get_by_id(line.camera_id)
    if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return line


class CountingController:
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str) -> list[dict]:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        return [c.to_dict() for c in CountingLine.get_for_camera(camera.id, enabled_only=False)]

    @classmethod
    def create(cls, user, camera_uuid: str, data: dict) -> dict:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        _validate(data)
        return CountingLine.create(camera.id, data, user.id).to_dict()

    @classmethod
    def update(cls, user, line_id, data: dict) -> dict:
        _guard()
        line = _require(user, line_id)
        if any(k in data for k in ('geometry', 'kind', 'name')):
            _validate({**line.to_dict(), **data})
        return line.modify(data, user.id).to_dict()

    @classmethod
    def delete(cls, user, line_id):
        _guard()
        _require(user, line_id).soft_delete()

    @classmethod
    def analytics(cls, user, args) -> dict:
        _guard()
        camera = _scoped_camera(user, args.get('camera_id') or args.get('camera_uuid'))
        from server.util.tool import safe_int
        line_id = safe_int(args.get('line_id'), None) if args.get('line_id') else None
        rows = CountingStat.query(camera.id, line_id, _parse_ms(args.get('start')), _parse_ms(args.get('end')))
        return {'count': len(rows), 'items': [r.to_dict() for r in rows]}
