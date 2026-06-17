"""P3 event_outbox consumer (PLAN P5 §6.1) — the primary trigger source. Polls pending rows,
normalizes to TriggerEvent, runs the rule engine + notification router + external webhook
subscriptions, then marks the row consumed (at-least-once; idempotency dedups)."""
import logging

from server.model import db
from server.model.event_outbox import STATUS_FAILED, EventOutbox
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@app.task(name='server.task.list.outbox_consumer.consume')
@celery_use_db()
def consume():
    from server.controller.external import ExternalController
    from server.service import notification_router, rule_dispatcher, trigger_router

    rows = EventOutbox.get_pending(limit=100)
    for row in rows:
        try:
            trig = trigger_router.from_outbox(row)
            rule_dispatcher.on_trigger(trig)               # automation rules
            notification_router.route_event(row.payload)   # user notifications
            ExternalController.deliver_subscriptions(row.payload)  # external webhook subscriptions
            row.mark_consumed()
        except Exception:
            logger.exception('outbox consume failed (row %s)', row.id)
            db.session.rollback()
            try:
                row.attempts = (row.attempts or 0) + 1
                if row.attempts >= MAX_ATTEMPTS:    # poison row — stop re-running it forever
                    row.status = STATUS_FAILED
                    logger.error('outbox row %s marked failed after %d attempts', row.id, row.attempts)
                db.session.add(row)
                db.session.commit()
            except Exception:
                db.session.rollback()
    return len(rows)
