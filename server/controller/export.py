from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.audit_log import AuditLog
from server.model.camera import Camera
from server.model.export_job import MODE_COPY, MODE_TRANSCODE, STATUS_DONE, STATUS_QUEUED, ExportJob
from server.service.permission import PermissionService


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


class ExportController:
    @classmethod
    def create_job(cls, data: dict, actor) -> dict:
        camera_uuid = data.get('camera_uuid')
        if not camera_uuid:
            raise InvalidParameterException('camera_uuid required')
        camera = Camera.get_by_uuid(camera_uuid)
        if not PermissionService.has_camera_scope(actor, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')

        start = _parse_ms(data.get('start_ts'))
        end = _parse_ms(data.get('end_ts'))
        if not start or not end or end <= start:
            raise InvalidParameterException('valid start_ts/end_ts (epoch ms) required')
        if (end - start).total_seconds() > 6 * 3600:
            raise InvalidParameterException('export window too large (max 6h)')

        mode = data.get('mode') or MODE_COPY
        if mode not in (MODE_COPY, MODE_TRANSCODE):
            raise InvalidParameterException('mode must be copy or transcode')

        # P6 R3 — watermark (force re-encode) + optional AES-zip password; both flag-gated.
        watermark = bool(data.get('watermark'))
        password = (data.get('password') or '').strip()
        if (watermark or password):
            from server.service import feature_flag
            if not feature_flag.is_enabled('export_watermark'):
                raise InvalidParameterException('feature_disabled')
        if watermark:
            mode = MODE_TRANSCODE

        enc_password, enc_key_id = (None, None)
        if password:
            from server.util.crypto import encrypt_credential
            enc_password, enc_key_id = encrypt_credential(password)

        job = ExportJob.create(
            camera_id=camera.id, requested_by_id=actor.id, start_ts=start, end_ts=end,
            mode=mode, container=data.get('container') or 'mp4',
            transcode_preset=data.get('transcode_preset'),
            watermark=watermark, watermark_text=data.get('watermark_text'),
            password_protected=bool(password), enc_password=enc_password, enc_key_id=enc_key_id)

        from server.task.list.transcode import run_export_job
        async_result = run_export_job.delay(str(job.id))
        job.update(celery_task_id=async_result.id)
        AuditLog.record('export_created', target=str(job.id), user_id=actor.id)
        return {'job_id': str(job.id), 'status': STATUS_QUEUED}

    @classmethod
    def get_job(cls, job_id, actor) -> dict:
        job = cls._owned_job(job_id, actor)
        return job.to_dict(with_token=True)

    @classmethod
    def list_jobs(cls, actor, page, items_per_page) -> tuple[int, list[dict]]:
        total, rows = ExportJob.list_for_user(actor.id, page, items_per_page)
        return total, [j.to_dict(with_token=True) for j in rows]

    @classmethod
    def cancel_job(cls, job_id, actor):
        job = cls._owned_job(job_id, actor)
        if job.celery_task_id:
            try:
                from server.task.celery import app
                app.control.revoke(job.celery_task_id, terminate=True)
            except Exception:
                pass
        cls._cleanup_output(job)
        job.update(status='failed', error_message='cancelled')
        AuditLog.record('export_cancelled', target=str(job.id), user_id=actor.id)

    @classmethod
    def resolve_download(cls, token: str, actor) -> tuple[ExportJob, str]:
        job = ExportJob.get_by_token(token)
        if not job or job.status != STATUS_DONE:
            raise RowNotFoundException()
        if job.requested_by_id != actor.id and not PermissionService.is_superuser(actor):
            raise NoPermissionException('download_denied')
        from server.model.disk import Disk
        from server.service import storage_manager
        disk = Disk.get_by_id(job.output_disk_id) if job.output_disk_id else None
        if not disk or not job.output_rel_path:
            raise RowNotFoundException()
        import os
        path = storage_manager.abs_path(disk, job.output_rel_path)
        if not os.path.exists(path):
            raise RowNotFoundException()
        return job, path

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _owned_job(job_id, actor) -> ExportJob:
        job = ExportJob.get_by_id(int(job_id))
        if not job:
            raise RowNotFoundException()
        if job.requested_by_id != actor.id and not PermissionService.is_superuser(actor):
            raise NoPermissionException('export_access_denied')
        return job

    @staticmethod
    def _cleanup_output(job: ExportJob):
        if not job.output_disk_id or not job.output_rel_path:
            return
        import os
        from server.model.disk import Disk
        from server.service import storage_manager
        disk = Disk.get_by_id(job.output_disk_id)
        if disk:
            try:
                os.unlink(storage_manager.abs_path(disk, job.output_rel_path))
            except OSError:
                pass
