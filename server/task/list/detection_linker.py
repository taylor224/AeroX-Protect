"""Backfill detection.segment_id for detections whose segment was indexed late (§5.6)."""
import logging

from server.service import segment_linker
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.detection_linker.backfill_segments')
@celery_use_db()
def backfill_segments():
    linked = segment_linker.backfill(limit=1000)
    if linked:
        logger.info('detection_linker: linked %d detections to segments', linked)
    return linked
