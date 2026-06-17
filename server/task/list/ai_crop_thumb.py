"""Detection crop/thumbnail generation (PLAN P4 §5.1). Search thumbnails are served
on-demand by GET /detections/{id}/snapshot (P2 frame extraction), so persistent crop
storage (ai_settings.store_crops) is the optional path wired here for later."""
import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.ai_crop_thumb.generate_crop')
@celery_use_db()
def generate_crop(detection_id: str):
    """Placeholder for store_crops=on persistent crops. On-demand snapshots cover MVP."""
    logger.debug('ai_crop_thumb.generate_crop(%s) — on-demand snapshot covers MVP', detection_id)
    return None
