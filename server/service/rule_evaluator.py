"""Rule evaluation (PLAN P5 §5.5). Trigger-detail + AND-group condition matching (pure),
plus cooldown / rate-limit / idempotency via Redis. time_ranges/quiet are interpreted in
KST (dow 1=Mon..7=Sun). Clause ops are a whitelist — no eval/SSTI."""
from dataclasses import dataclass
from datetime import datetime

import config
from server.model import KST

# clause op whitelist
_OPS = {
    'eq': lambda a, b: a == b,
    'ne': lambda a, b: a != b,
    'gt': lambda a, b: _num(a) > _num(b),
    'gte': lambda a, b: _num(a) >= _num(b),
    'lt': lambda a, b: _num(a) < _num(b),
    'lte': lambda a, b: _num(a) <= _num(b),
    'in': lambda a, b: a in (b or []),
    'not_in': lambda a, b: a not in (b or []),
}


@dataclass
class Result:
    matched: bool
    reason: str | None = None


def evaluate(rule, trig) -> Result:
    if not rule.enabled:
        return Result(False, 'disabled')

    t = rule.trigger or {}
    if rule.trigger_type == 'event':
        if t.get('event_types') and trig.type not in t['event_types']:
            return Result(False, 'condition_false')
        if t.get('subtypes') and trig.subtype not in t['subtypes']:
            return Result(False, 'condition_false')
        # face-of-person: restrict to specific identities (empty/absent = any identity)
        if t.get('identity_ids') and trig.identity_id not in _int_list(t['identity_ids']):
            return Result(False, 'condition_false')
    elif rule.trigger_type == 'object':
        if t.get('classes') and not (set(trig.classes or []) & set(t['classes'])):
            return Result(False, 'condition_false')
        if t.get('min_confidence') and (trig.score or 0) < t['min_confidence']:
            return Result(False, 'condition_false')
    elif rule.trigger_type == 'system_event':
        # event_types = which lifecycle events fire this rule (camera_offline, io_input_on, …)
        if t.get('event_types') and trig.type not in t['event_types']:
            return Result(False, 'condition_false')

    c = rule.condition or {}
    if c.get('camera_ids') and trig.camera_id not in _int_list(c['camera_ids']):
        return Result(False, 'condition_false')
    if c.get('device_ids') and trig.device_id not in _int_list(c['device_ids']):
        return Result(False, 'condition_false')
    if c.get('min_score') and (trig.score or 0) < c['min_score']:
        return Result(False, 'condition_false')
    if c.get('time_ranges') and not in_time_ranges(trig.ts, c['time_ranges']):
        return Result(False, 'condition_false')
    if c.get('quiet_respect') and c.get('quiet_hours') and in_quiet(trig.ts, c['quiet_hours']):
        return Result(False, 'quiet_hours')
    if c.get('all_of') and not all(match_clause(cl, trig) for cl in c['all_of']):
        return Result(False, 'condition_false')
    if c.get('any_of') and not any(match_clause(cl, trig) for cl in c['any_of']):
        return Result(False, 'condition_false')
    if c.get('correlate'):
        from server.service import correlation
        if not correlation.matches(c['correlate'], trig):
            return Result(False, 'correlation_unmet')

    if _within_cooldown(rule, trig):
        return Result(False, 'cooldown')
    if rule.max_per_hour and _over_rate(rule, trig, rule.max_per_hour):
        return Result(False, 'rate_limited')
    return Result(True, None)


# ── clause + time helpers (pure) ────────────────────────────────────────────────
def match_clause(clause: dict, trig) -> bool:
    field = clause.get('field')
    op = _OPS.get(clause.get('op'))
    if op is None:
        return False
    value = clause.get('value')
    actual = {
        'score': trig.score, 'camera_id': trig.camera_id, 'type': trig.type, 'subtype': trig.subtype,
        'object_class': (trig.classes or [None])[0],
        'identity_id': trig.identity_id, 'identity': trig.identity_name, 'device_id': trig.device_id,
    }.get(field)
    if field == 'object_class' and clause.get('op') in ('in', 'not_in'):
        hit = bool(set(trig.classes or []) & set(value or []))
        return hit if clause['op'] == 'in' else not hit
    try:
        return bool(op(actual, value))
    except (TypeError, ValueError):
        return False


def in_time_ranges(ts_ms: int | None, ranges: list) -> bool:
    if ts_ms is None:
        return True
    kst = datetime.fromtimestamp(ts_ms / 1000, KST)
    dow = kst.isoweekday()                      # 1=Mon .. 7=Sun
    minute = kst.hour * 60 + kst.minute
    for r in ranges or []:
        if r.get('dow') and dow not in r['dow']:
            continue
        start = _hhmm(r.get('start', '00:00'))
        end = _hhmm(r.get('end', '24:00'))
        if start <= end:
            if start <= minute < end:
                return True
        else:                                   # crosses midnight
            if minute >= start or minute < end:
                return True
    return False


def in_quiet(ts_ms: int | None, quiet: dict) -> bool:
    return in_time_ranges(ts_ms, [{'start': rg.get('start'), 'end': rg.get('end')} for rg in (quiet or {}).get('ranges', [])])


# ── cooldown / rate / idempotency (Redis) ───────────────────────────────────────
def scope_key(rule, trig) -> str:
    if rule.dedup_scope == 'rule':
        return 'r'
    if rule.dedup_scope == 'target':
        return 'c%s:e%s' % (trig.camera_id, trig.event_id)
    return 'c%s' % trig.camera_id               # default: camera


def idem_key(rule, trig) -> str:
    return '%s:%s:%s' % (rule.id, scope_key(rule, trig), trig.event_id or trig.ts)


def _redis():
    from server.service.token import get_redis
    return get_redis()


def _cd_key(rule, trig) -> str:
    return '%s:rule:cd:%s:%s' % (config.REDIS_KEY_PREFIX, rule.id, scope_key(rule, trig))


def _within_cooldown(rule, trig) -> bool:
    window = max(rule.cooldown_s or 0, rule.debounce_s or 0)
    if window <= 0:
        return False
    try:
        return _redis().exists(_cd_key(rule, trig)) == 1
    except Exception:
        return False


def mark_cooldown(rule, trig):
    window = max(rule.cooldown_s or 0, rule.debounce_s or 0)
    if window <= 0:
        return
    try:
        _redis().setex(_cd_key(rule, trig), window, '1')
    except Exception:
        pass


def claim_idempotency(rule, trig) -> bool:
    """SET NX — returns True if this is the first time (not a duplicate)."""
    try:
        key = '%s:rule:idem:%s' % (config.REDIS_KEY_PREFIX, idem_key(rule, trig))
        return bool(_redis().set(key, '1', nx=True, ex=max(60, rule.cooldown_s or 60)))
    except Exception:
        return True


def _over_rate(rule, trig, max_per_hour: int) -> bool:
    try:
        key = '%s:rule:rate:%s' % (config.REDIS_KEY_PREFIX, rule.id)
        n = _redis().incr(key)
        if n == 1:
            _redis().expire(key, 3600)
        return n > max_per_hour
    except Exception:
        return False


# ── tiny utils ──────────────────────────────────────────────────────────────────
def _hhmm(s: str) -> int:
    try:
        h, m = s.split(':')
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _num(v):
    return float(v) if v is not None else 0.0


def _int_list(xs):
    out = []
    for x in xs or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out
