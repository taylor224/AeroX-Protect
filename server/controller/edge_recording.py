"""Edge-recording import (PLAN P6 R6). Camera-scoped; flag-gated by `edge_recording`.
Previews timeline gaps and queues a gap-fill import of the camera's SD clips via Celery.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException
from server.model import UTC
from server.model.camera import Camera
from server.model.edge_import_job import EdgeImportJob
from server.service import edge_recording, feature_flag
from server.service.permission import PermissionService

MAX_RANGE_HOURS = 24          # one import job spans at most a day (bound search/download)


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard():
    if not feature_flag.is_enabled('edge_recording'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    camera = Camera.get_by_uuid(camera_uuid)
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _range(data: dict) -> tuple[datetime, datetime]:
    start = _parse_ms(data.get('range_start'))
    end = _parse_ms(data.get('range_end'))
    if start is None or end is None:
        raise InvalidParameterException('range_start and range_end (epoch ms) required')
    if end <= start:
        raise InvalidParameterException('range_end must be after range_start')
    if (end - start).total_seconds() > MAX_RANGE_HOURS * 3600:
        raise InvalidParameterException('range too large (max %dh)' % MAX_RANGE_HOURS)
    return start, end


class EdgeRecordingController:
    @classmethod
    def preview_gaps(cls, user, camera_uuid: str, args) -> dict:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        start, end = _range({'range_start': args.get('start'), 'range_end': args.get('end')})
        return {'gaps': edge_recording.gaps_preview(camera.id, start, end)}

    @classmethod
    def list_jobs(cls, user, camera_uuid: str) -> list[dict]:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        return [j.to_dict() for j in EdgeImportJob.list_for_camera(camera.id)]

    @classmethod
    def create_import(cls, user, camera_uuid: str, data: dict) -> dict:
        _guard()
        camera = _scoped_camera(user, camera_uuid)
        if not camera.edge_recording:
            raise InvalidParameterException('edge_recording not enabled for this camera')
        start, end = _range(data)
        job = EdgeImportJob.create(camera.id, start, end, user.id)
        try:
            from server.task.list.edge_import import run_edge_import
            res = run_edge_import.delay(str(job.id))
            job.update(celery_task_id=res.id)
        except Exception:                      # broker down → leave queued, surface job anyway
            pass
        return job.to_dict()
