import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.retention.run_retention')
@celery_use_db()
def run_retention():
    """Per-minute: days + capacity + disk-free rotation (PLAN P2 §6.9)."""
    from server.service.retention_engine import run_retention as _run
    result = _run()
    if any(result.values()):
        logger.info('retention: %s', result)
    return result
