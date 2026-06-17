from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.camera import Camera
from server.model.detection_zone import KINDS, DetectionZone
from server.service import ai_scheduler
from server.service.permission import PermissionService


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _validate(data: dict):
    poly = data.get('polygon')
    if not isinstance(poly, list) or len(poly) < 3:
        raise InvalidParameterException('polygon needs ≥3 points')
    if data.get('kind') and data['kind'] not in KINDS:
        raise InvalidParameterException('kind must be one of %s' % (KINDS,))
    if not data.get('name'):
        raise InvalidParameterException('name required')


class DetectionZoneController:
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str) -> list[dict]:
        camera = _scoped_camera(user, camera_uuid)
        return [z.to_dict() for z in DetectionZone.get_for_camera(camera.id, enabled_only=False)]

    @classmethod
    def create(cls, user, camera_uuid: str, data: dict) -> dict:
        camera = _scoped_camera(user, camera_uuid)
        _validate(data)
        z = DetectionZone.create(camera.id, data, user.id)
        ai_scheduler.touch()
        return z.to_dict()

    @classmethod
    def update(cls, user, zone_id: int, data: dict) -> dict:
        z = DetectionZone.get_by_id(zone_id)
        if not z:
            raise RowNotFoundException()
        camera = Camera.get_by_id(z.camera_id)
        if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        if 'polygon' in data or 'kind' in data or 'name' in data:
            _validate({**z.to_dict(), **data})
        z.modify(data, user.id)
        ai_scheduler.touch()
        return z.to_dict()

    @classmethod
    def delete(cls, user, zone_id: int):
        z = DetectionZone.get_by_id(zone_id)
        if not z:
            raise RowNotFoundException()
        camera = Camera.get_by_id(z.camera_id)
        if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        z.soft_delete()
        ai_scheduler.touch()
