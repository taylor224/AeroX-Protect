import logging

from server.model import utcnow
from server.model.refresh_token import RefreshToken
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.maintenance.cleanup_expired_tokens')
@celery_use_db()
def cleanup_expired_tokens():
    """Daily: purge expired refresh-token family rows (Redis denylist self-expires)."""
    deleted = RefreshToken.delete_expired(utcnow())
    logger.info('cleanup_expired_tokens: deleted %d expired refresh tokens', deleted)
    return deleted
