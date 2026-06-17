from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.camera import Camera
from server.model.timelapse_job import STATUS_DONE, TimelapseJob
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _parse_ms(value):
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


class TimelapseController:
    @classmethod
    def list_jobs(cls, camera_uuid, status, page, items_per_page) -> tuple[int, list[dict]]:
        camera_id = Camera.get_by_uuid(camera_uuid).id if camera_uuid else None
        total, rows = TimelapseJob.list_for(camera_id, status, page, items_per_page)
        return total, [j.to_dict() for j in rows]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        camera = Camera.get_by_uuid(data.get('camera_uuid', ''))
        if not PermissionService.has_camera_scope(actor, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        start = _parse_ms(data.get('range_start'))
        end = _parse_ms(data.get('range_end'))
        if not start or not end or end <= start:
            raise InvalidParameterException('valid range_start/range_end (epoch ms) required')
        speed = safe_int(data.get('speed_factor'), 60)
        if speed < 1 or speed > 3600:
            raise InvalidParameterException('speed_factor out of range')
        job = TimelapseJob.create(
            camera_id=camera.id, range_start=start, range_end=end,
            source=data.get('source') or 'range', speed_factor=speed,
            params=data.get('params'), event_ids=data.get('event_ids'), actor_id=actor.id)
        from server.task.list.timelapse import run_timelapse
        res = run_timelapse.delay(str(job.id))
        job.update(celery_task_id=res.id)
        return job.to_dict()

    @classmethod
    def get_job(cls, job_id: int, actor) -> dict:
        return cls._owned(job_id, actor).to_dict()

    @classmethod
    def cancel(cls, job_id: int, actor):
        job = cls._owned(job_id, actor)
        if job.celery_task_id:
            try:
                from server.task.celery import app
                app.control.revoke(job.celery_task_id, terminate=True)
            except Exception:
                pass
        job.update(status='canceled')

    @classmethod
    def resolve_download(cls, job_id: int, actor):
        import os

        from server.model.disk import Disk
        from server.service import storage_manager
        job = cls._owned(job_id, actor)
        if job.status != STATUS_DONE or not job.output_path or not job.output_disk_id:
            raise RowNotFoundException()
        disk = Disk.get_by_id(job.output_disk_id)
        if not disk:
            raise RowNotFoundException()
        path = storage_manager.abs_path(disk, job.output_path)
        if not os.path.exists(path):
            raise RowNotFoundException()
        return job, path

    @staticmethod
    def _owned(job_id, actor) -> TimelapseJob:
        job = TimelapseJob.get_by_id(int(job_id))
        if not job:
            raise RowNotFoundException()
        camera = Camera.get_by_id(job.camera_id)
        if camera and not PermissionService.has_camera_scope(actor, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        return job
