"""Schedule-trigger rules (PLAN P5 §6.1). Beat every minute: match each schedule rule's cron
(KST) against the current minute and fire it."""
import logging
from datetime import datetime

from server.model import KST
from server.model.rule import TRIGGER_SCHEDULE, Rule
from server.service import rule_dispatcher, trigger_router
from server.task.celery import app, celery_use_db
from server.util.cron import cron_match

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.schedule_trigger.tick')
@celery_use_db()
def tick():
    now = datetime.now(KST)
    fired = 0
    for rule in Rule.active_for(TRIGGER_SCHEDULE):
        cron = (rule.trigger or {}).get('cron')
        if cron and cron_match(cron, now):
            trig = trigger_router.from_schedule()
            trig.trigger_type = 'schedule'
            rule_dispatcher.fire_rule(rule, trig)
            fired += 1
    if fired:
        logger.info('schedule_trigger: fired %d rules', fired)
    return fired
