"""Multi-event correlation for automation rules (AND/OR across events over a time window).

Every trigger that flows through the dispatcher is recorded into Redis keyed by
event-type (+ camera). A rule can then require that a *set* of events occurred within a
window — `all` of them (AND) or `any` of them (OR) — letting operators express things like
"motion on cam 1 AND door input on the IO module within 30s". Best-effort: a Redis hiccup
degrades to "not seen" rather than crashing rule evaluation.
"""
import config


def _redis():
    from server.service.token import get_redis
    return get_redis()


def _key(event_type: str, camera_id) -> str:
    return '%s:autocorr:%s:%s' % (config.REDIS_KEY_PREFIX, event_type, camera_id if camera_id is not None else '*')


def record(trig) -> None:
    """Stamp this trigger's (type, camera) as last-seen-now, with a bounded TTL."""
    et = trig.type or trig.trigger_type
    if not et:
        return
    try:
        r = _redis()
        ts = trig.ts or 0
        # record both the camera-specific and the any-camera bucket so a rule can match either
        for key in (_key(et, trig.camera_id), _key(et, None)):
            r.setex(key, 3600, str(ts))
    except Exception:
        pass


def seen_within(event_type: str, camera_id, window_s: int, now_ms: int) -> bool:
    """True if an event of `event_type` (on `camera_id`, or any camera if None) was recorded
    within the last `window_s` seconds."""
    try:
        raw = _redis().get(_key(event_type, camera_id))
    except Exception:
        return False
    if raw is None:
        return False
    try:
        seen_ms = int(raw)
    except (TypeError, ValueError):
        return False
    return (now_ms - seen_ms) <= max(1, window_s) * 1000


def matches(correlate: dict, trig) -> bool:
    """Evaluate a rule's `correlate` block against recently-recorded events.

    correlate = {window_s, mode: 'all'|'any', events: [{type, camera: <id>|'same'|'any'}]}
    'same' means the same camera as the current trigger; 'any' (or omitted) means any camera.
    """
    events = correlate.get('events') or []
    if not events:
        return True
    window_s = int(correlate.get('window_s') or 60)
    now_ms = trig.ts or 0
    mode = correlate.get('mode', 'all')

    def _hit(spec):
        cam_spec = spec.get('camera', 'any')
        cam = trig.camera_id if cam_spec == 'same' else (None if cam_spec in ('any', None) else cam_spec)
        return seen_within(spec.get('type'), cam, window_s, now_ms)

    results = [_hit(s) for s in events]
    return all(results) if mode == 'all' else any(results)
