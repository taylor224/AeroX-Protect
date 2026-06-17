"""Delete expired/consumed pairing codes (PLAN P5 §4.6)."""
import logging

from server.model.pairing_code import PairingCode
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.pairing_code_cleanup.cleanup')
@celery_use_db()
def cleanup():
    n = PairingCode.cleanup()
    if n:
        logger.info('pairing_code_cleanup: removed %d', n)
    return n
