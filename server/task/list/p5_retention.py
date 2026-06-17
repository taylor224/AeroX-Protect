"""rule_executions + notifications retention (PLAN P5 §4.2, §4.9)."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.notification import Notification
from server.model.rule_execution import RuleExecution
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)
EXEC_RETENTION_DAYS = 90
NOTIF_RETENTION_DAYS = 60


@app.task(name='server.task.list.p5_retention.run')
@celery_use_db()
def run():
    execs = RuleExecution.purge_older_than(utcnow() - timedelta(days=EXEC_RETENTION_DAYS))
    notifs = Notification.purge_older_than(utcnow() - timedelta(days=NOTIF_RETENTION_DAYS))
    if execs or notifs:
        logger.info('p5_retention: %d executions, %d notifications purged', execs, notifs)
    return {'rule_executions': execs, 'notifications': notifs}


@app.task(name='server.task.list.p5_retention.healthcheck_targets')
@celery_use_db()
def healthcheck_targets():
    from server.controller.action_target import ActionTargetController
    from server.model.action_target import ActionTarget
    checked = 0
    for t in ActionTarget.list_for():
        try:
            ActionTargetController.healthcheck(t.uuid)
            checked += 1
        except Exception:
            logger.exception('healthcheck failed for %s', t.uuid)
    return checked
