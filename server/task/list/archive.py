"""Archive offload task (PLAN P6 M2)."""
import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.archive.run_archive_job')
@celery_use_db()
def run_archive_job(job_id):
    from server.service import archiver
    archiver.run(int(job_id))
