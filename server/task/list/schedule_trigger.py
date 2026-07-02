"""Schedule-trigger flows. Beat every minute: match each flow's schedule trigger
source's cron (KST) against the current minute and fire it."""
import logging
from datetime import datetime

from server.model import KST
from server.service import flow_engine
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.schedule_trigger.tick')
@celery_use_db()
def tick():
    now = datetime.now(KST)
    fired = flow_engine.tick_schedules(now)
    if fired:
        logger.info('schedule_trigger: fired %d flows', fired)
    return fired
