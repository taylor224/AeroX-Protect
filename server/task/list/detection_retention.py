"""detections retention (PLAN P4 §4.6, §13). Batch-DELETE rows past retention_days. At
scale this becomes a monthly RANGE-partition DROP (§14 Q5); MVP is a bounded batch delete."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.ai_settings import AiSettings
from server.model.detection import Detection
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.detection_retention.purge_detections')
@celery_use_db()
def purge_detections():
    g = AiSettings.get_global()
    days = g.retention_days if g else 30
    cutoff = utcnow() - timedelta(days=days)
    deleted = Detection.purge_older_than(cutoff)
    if deleted:
        logger.info('detection_retention: purged %d detections older than %dd', deleted, days)
    return deleted
