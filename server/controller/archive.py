"""Archive targets + jobs (PLAN P6 M2). Flag-gated (`archiving`). Targets hold Fernet-
encrypted credentials; jobs offload a recording's segments via Celery.
"""
from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model.archive_job import SOURCE_RECORDING, STATUS_QUEUED, ArchiveJob
from server.model.archive_target import TYPES, ArchiveTarget
from server.service import feature_flag


def _guard():
    if not feature_flag.is_enabled('archiving'):
        raise NoPermissionException('feature_disabled')


class ArchiveController:
    @classmethod
    def list_targets(cls) -> list[dict]:
        _guard()
        return [t.to_dict() for t in ArchiveTarget.list_all()]

    @classmethod
    def create_target(cls, data: dict, actor) -> dict:
        _guard()
        if not data.get('name') or data.get('type') not in TYPES:
            raise InvalidParameterException('name and valid type (s3/smb/local) required')
        return ArchiveTarget.create(data, actor.id).to_dict()

    @classmethod
    def update_target(cls, target_id, data: dict, actor) -> dict:
        _guard()
        t = ArchiveTarget.get_by_id(target_id)
        if not t:
            raise RowNotFoundException()
        return t.modify(data, actor.id).to_dict()

    @classmethod
    def delete_target(cls, target_id):
        _guard()
        t = ArchiveTarget.get_by_id(target_id)
        if not t:
            raise RowNotFoundException()
        t.soft_delete()

    @classmethod
    def list_jobs(cls) -> list[dict]:
        _guard()
        return [j.to_dict() for j in ArchiveJob.list_all()]

    @classmethod
    def create_job(cls, data: dict, actor) -> dict:
        _guard()
        target_id, source_ref = data.get('target_id'), data.get('source_ref')
        if not target_id or not source_ref:
            raise InvalidParameterException('target_id and source_ref required')
        target = ArchiveTarget.get_by_id(target_id)
        if not target or not target.enabled:
            raise InvalidParameterException('target not found or disabled')
        job = ArchiveJob.create(target.id, data.get('source_type') or SOURCE_RECORDING, source_ref, actor.id)
        from server.task.list.archive import run_archive_job
        res = run_archive_job.delay(str(job.id))
        job.update(celery_task_id=res.id)
        return {'job_id': str(job.id), 'status': STATUS_QUEUED}
