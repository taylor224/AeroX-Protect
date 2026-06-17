"""Event processing pipeline (PLAN §5.6, §5.7). One raw vendor event →
normalize → state machine/dedup → policy → schedule combine → record/notify → outbox.

start_ts uses the server receive time (§6.6 trust_clock=false default) — consistent
with the P2 cache (recorder uses container UTC), so pre/post buffer recovery is exact.
"""
import logging

import config
from server.model import db, utcnow
from server.model.event import STATE_ACTIVE, STATE_ENDED, STATE_PULSE, TYPE_MOTION, Event
from server.model.event_outbox import EventOutbox
from server.model.event_policy import ACTION_DISCARD, ACTION_NOTIFY_ONLY, ACTION_RECORD, ACTION_TIMELAPSE
from server.model.schedule import MODE_MOTION_ONLY, MODE_OFF
from server.service import event_normalizer, event_policy_resolver, schedule_resolver

logger = logging.getLogger(__name__)
MOTION_TYPES = {TYPE_MOTION}


def combine(action: str, mode: str, event_type: str) -> str:
    """Policy action × schedule mode → final action (PLAN §5.7 table)."""
    if action == ACTION_DISCARD:
        return 'discard'
    if action == ACTION_NOTIFY_ONLY:
        if mode == MODE_MOTION_ONLY and event_type not in MOTION_TYPES:
            return 'discard'
        return 'notify_only'
    if action == ACTION_TIMELAPSE:
        if mode == MODE_OFF:
            return 'discard'
        if mode == MODE_MOTION_ONLY and event_type not in MOTION_TYPES:
            return 'discard'
        return 'timelapse'
    if action == ACTION_RECORD:
        if mode == MODE_OFF:
            return 'discard'
        if mode == MODE_MOTION_ONLY and event_type not in MOTION_TYPES:
            return 'discard'
        return 'record'
    return 'discard'


def _cooldown_key(dedup: str) -> str:
    return '%s:event:cooldown:%s' % (config.REDIS_KEY_PREFIX, dedup)


def _within_cooldown(dedup: str) -> bool:
    try:
        from server.service.token import get_redis
        return get_redis().exists(_cooldown_key(dedup)) == 1
    except Exception:
        return False


def _mark_trigger(dedup: str, cooldown_s: int):
    try:
        from server.service.token import get_redis
        get_redis().setex(_cooldown_key(dedup), max(1, cooldown_s), '1')
    except Exception:
        pass


def handle(camera, raw: dict, source: str) -> Event | None:
    n = event_normalizer.normalize(camera, raw, source)
    if n is None:
        return None
    return _process(camera, n, source, raw)


def ingest_object(camera_id: int, normalized: dict) -> Event | None:
    """P4 adapter (PLAN §6.8): a detection trigger promotes an object to a P3 event
    (type='object', source='server'). Same policy→schedule→record/notify path as handle()."""
    from server.model.camera import Camera
    camera = Camera.get_by_id(camera_id)
    if not camera:
        return None
    n = event_normalizer.NormalizedEvent(
        type=normalized.get('type', 'object'),
        state=normalized.get('state', 'pulse'),
        subtype=normalized.get('subtype'),
        ts=normalized.get('ts'),
        score=normalized.get('score'),
        channel=normalized.get('channel'),
        region=normalized.get('region'),
        dedup_extra=normalized.get('dedup_extra'))
    return _process(camera, n, normalized.get('source', 'server'), normalized.get('raw') or {})


def _process(camera, n, source: str, raw: dict) -> Event | None:
    if n.vendor_event_id and Event.exists_vendor(camera.id, n.vendor_event_id):
        return None

    now = utcnow()
    dedup = '%s:%s:%s:%s' % (camera.id, n.type, n.subtype, n.channel)
    if n.dedup_extra:                  # distinct identities (plate/face/door) get distinct
        dedup += ':%s' % n.dedup_extra  # cooldown keys so concurrent alerts aren't collapsed

    # ── state machine ─────────────────────────────────────────────────────────
    if n.state == 'start':
        active = Event.get_active_by_dedup(dedup)
        if active:
            return active                                    # duplicate start absorbed
        ev = _create(camera, n, source, dedup, now, STATE_ACTIVE, raw)
    elif n.state == 'end':
        ev = Event.get_active_by_dedup(dedup)
        if not ev:
            ev = _create(camera, n, source, dedup, now, STATE_ENDED, raw)
        ev.close(end_ts=now)
    else:
        ev = _create(camera, n, source, dedup, now, STATE_PULSE, raw)

    # ── policy ────────────────────────────────────────────────────────────────
    policy = event_policy_resolver.resolve(camera.id, n.type, n.subtype, at_ts=ev.start_ts)
    if policy is None or not policy.enabled:
        return ev
    if policy.min_score is not None and (n.score or 0) < policy.min_score:
        _set_action(ev, 'discard:score')
        return ev
    if _within_cooldown(dedup):
        _set_action(ev, 'discard:cooldown')
        return ev

    sched_mode = schedule_resolver.mode(camera.id, ev.start_ts)
    action = combine(policy.action, sched_mode, n.type)
    _set_action(ev, action)

    if action == 'record':
        from server.service import event_clip
        event_clip.materialize(ev.id, policy.pre_buffer_s, policy.post_buffer_s, policy.retention_class)
        _mark_trigger(dedup, policy.cooldown_s)

    # 'discard' = schedule turned this event off entirely — no recording AND no
    # notification traffic (notify-without-record is the explicit notify_only action)
    if action != 'discard' and (policy.notify or action == 'notify_only'):
        EventOutbox.publish(ev)   # P5 consumes (at-least-once)

    return ev


def _create(camera, n, source, dedup, ts, state, raw) -> Event:
    return Event.create(
        camera_id=camera.id, type=n.type, source=source, dedup_key=dedup, start_ts=ts, state=state,
        subtype=n.subtype, score=n.score, channel=n.channel, region=n.region,
        vendor_event_id=n.vendor_event_id, raw=raw)


def _set_action(ev: Event, action: str):
    ev.policy_action = action
    db.session.add(ev)
    db.session.commit()
