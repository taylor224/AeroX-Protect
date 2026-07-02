"""flow_runs retention + action-target healthchecks (PLAN P5 §4.2)."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.flow_run import FlowRun
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)
EXEC_RETENTION_DAYS = 90


@app.task(name='server.task.list.p5_retention.run')
@celery_use_db()
def run():
    flow_runs = FlowRun.purge_older_than(utcnow() - timedelta(days=EXEC_RETENTION_DAYS))
    if flow_runs:
        logger.info('p5_retention: %d flow runs purged', flow_runs)
    return {'flow_runs': flow_runs}


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
