"""Audio-detection read API (PLAN P6 A4). Camera-scoped recent classifications + the
label vocabulary for the UI. Flag-gated by `audio_detection`.
"""
from server.exception import NoPermissionException
from server.model.audio_detection import AudioDetection
from server.model.camera import Camera
from server.service import audio_classify, feature_flag
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _guard():
    if not feature_flag.is_enabled('audio_detection'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


class AudioDetectionController:
    @classmethod
    def list_for_camera(cls, user, camera_uuid: str, args) -> list[dict]:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        limit = min(safe_int(args.get('limit'), 50) or 50, 200)
        return [d.to_dict() for d in AudioDetection.recent_for_camera(camera.id, limit)]

    @classmethod
    def labels(cls) -> dict:
        _guard()
        return {'labels': audio_classify.LABELS, 'backend': audio_classify.active_backend()}
