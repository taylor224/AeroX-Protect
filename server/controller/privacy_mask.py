"""Privacy mask CRUD (PLAN P6 L2). Camera-scoped, flag-gated (`privacy_masks`). Mirrors
the detection-zone controller.
"""
from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.camera import Camera
from server.model.privacy_mask import MODES, PrivacyMask
from server.service import feature_flag
from server.service.permission import PermissionService


def _guard_flag():
    if not feature_flag.is_enabled('privacy_masks'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _validate(data: dict):
    poly = data.get('polygon')
    if not isinstance(poly, list) or len(poly) < 3:
        raise InvalidParameterException('polygon needs ≥3 points')
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in poly):
        raise InvalidParameterException('polygon points must be [x, y]')
    if data.get('mode') and data['mode'] not in MODES:
        raise InvalidParameterException('mode must be one of %s' % (MODES,))
    if not data.get('name'):
        raise InvalidParameterException('name required')


def _require(user, mask_id) -> PrivacyMask:
    m = PrivacyMask.get_by_id(mask_id)
    if not m:
        raise RowNotFoundException()
    camera = Camera.get_by_id(m.camera_id)
    if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return m


class PrivacyMaskController:
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str) -> list[dict]:
        _guard_flag()
        camera = _scoped_camera(user, camera_uuid)
        return [m.to_dict() for m in PrivacyMask.get_for_camera(camera.id)]

    @classmethod
    def create(cls, user, camera_uuid: str, data: dict) -> dict:
        _guard_flag()
        camera = _scoped_camera(user, camera_uuid)
        _validate(data)
        return PrivacyMask.create(camera.id, data, user.id).to_dict()

    @classmethod
    def update(cls, user, mask_id, data: dict) -> dict:
        _guard_flag()
        m = _require(user, mask_id)
        if 'polygon' in data or 'name' in data or 'mode' in data:
            _validate({**m.to_dict(), **data})
        return m.modify(data, user.id).to_dict()

    @classmethod
    def delete(cls, user, mask_id):
        _guard_flag()
        _require(user, mask_id).soft_delete()
