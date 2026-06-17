"""Event maintenance (PLAN §6.7, §13): force-end stale active events + retention."""
import logging
from datetime import timedelta

from server.model import db, utcnow
from server.model.event import Event
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)

MAX_ACTIVE_AGE_S = 120        # active events without an end after this → force-closed
EVENT_RETENTION_DAYS = 90     # soft-delete event metadata after this


@app.task(name='server.task.list.event_maintenance.active_event_sweeper')
@celery_use_db()
def active_event_sweeper():
    """Force-end active events that never received an end (ISAPI active-only / drop)."""
    cutoff = utcnow() - timedelta(seconds=MAX_ACTIVE_AGE_S)
    closed = 0
    for ev in Event.get_stale_active(cutoff, limit=1000):
        ev.close(end_ts=utcnow())
        closed += 1
    if closed:
        logger.info('active_event_sweeper: closed %d', closed)
    return closed


@app.task(name='server.task.list.event_maintenance.cleanup_events')
@celery_use_db()
def cleanup_events():
    """Soft-delete event metadata past retention."""
    cutoff = utcnow() - timedelta(days=EVENT_RETENTION_DAYS)
    deleted = db.session.query(Event).filter(
        Event.start_ts < cutoff, Event.deleted_at.is_(None)).update(
        {Event.deleted_at: utcnow()}, synchronize_session=False)
    db.session.commit()
    if deleted:
        logger.info('cleanup_events: soft-deleted %d', deleted)
    return deleted
