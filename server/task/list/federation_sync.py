"""Periodic federation sync (PLAN P8) — refresh every enabled member's camera cache + status."""
import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.federation_sync.sync')
@celery_use_db()
def sync():
    from server.service import federation, feature_flag
    if not feature_flag.is_enabled('federation'):
        return {'skipped': 'disabled'}
    return federation.sync_all()
