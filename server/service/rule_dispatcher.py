"""Rule dispatch (PLAN P5 §5.5). on_trigger evaluates active rules in priority order, logs a
rule_execution per rule, enforces idempotency/cooldown, and runs matched actions. Runs
synchronously inside the worker task (outbox_consumer / schedule_trigger / manual)."""
import logging

from server.model import db, utcnow
from server.model.rule import Rule
from server.model.rule_execution import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    RuleExecution,
)
from server.service import action_runner, correlation, rule_evaluator

logger = logging.getLogger(__name__)


def on_trigger(trig) -> list[RuleExecution]:
    correlation.record(trig)         # make this event available to other rules' correlate windows
    out = []
    for r in Rule.active_for(trig.trigger_type):
        res = rule_evaluator.evaluate(r, trig)
        if not res.matched:
            out.append(RuleExecution.create(
                rule_id=r.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
                camera_id=trig.camera_id, matched=False, status=STATUS_SKIPPED, skip_reason=res.reason))
            continue
        if not rule_evaluator.claim_idempotency(r, trig):
            out.append(RuleExecution.create(
                rule_id=r.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
                camera_id=trig.camera_id, matched=True, status=STATUS_SKIPPED, skip_reason='duplicate'))
            continue
        rule_evaluator.mark_cooldown(r, trig)
        ex = RuleExecution.create(
            rule_id=r.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
            camera_id=trig.camera_id, matched=True, idempotency_key=rule_evaluator.idem_key(r, trig),
            status=STATUS_RUNNING, started_ts=utcnow())
        r.last_triggered_ts = utcnow()
        db.session.add(r)
        db.session.commit()

        results = action_runner.run_all(r, trig)
        finished = utcnow()
        ex.update(action_results=results, status=_summarize(results), finished_ts=finished,
                  duration_ms=int((finished - ex.started_ts).total_seconds() * 1000) if ex.started_ts else None)
        out.append(ex)
        if r.stop_on_match:
            break
    return out


def fire_rule(rule, trig) -> RuleExecution:
    """Run a single rule's actions directly (manual trigger / test-fire) and log it."""
    ex = RuleExecution.create(
        rule_id=rule.id, trigger_type=trig.trigger_type, event_id=trig.event_id,
        camera_id=trig.camera_id, matched=True, status=STATUS_RUNNING, started_ts=utcnow())
    results = action_runner.run_all(rule, trig)
    finished = utcnow()
    ex.update(action_results=results, status=_summarize(results), finished_ts=finished,
              duration_ms=int((finished - ex.started_ts).total_seconds() * 1000) if ex.started_ts else None)
    return ex


def _summarize(results: list) -> str:
    if not results:
        return STATUS_SUCCESS
    statuses = [x.get('status') for x in results]
    if all(s == 'success' for s in statuses):
        return STATUS_SUCCESS
    if any(s == 'success' for s in statuses):
        return STATUS_PARTIAL
    return STATUS_FAILED
