"""Edge-recording gap-fill import task (PLAN P6 R6)."""
import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.edge_import.run_edge_import')
@celery_use_db()
def run_edge_import(job_id):
    from server.service import edge_recording
    edge_recording.run_import(int(job_id))


@app.task(name='server.task.list.edge_import.edge_auto_import_scan')
@celery_use_db()
def edge_auto_import_scan():
    """Beat task: queue gap-fill imports for cameras with auto-import enabled."""
    from server.service import edge_recording
    n = edge_recording.auto_import_due()
    if n:
        logger.info('edge_auto_import_scan: queued %d import(s)', n)
    return n
