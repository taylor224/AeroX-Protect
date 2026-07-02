"""Clause matching for flow condition nodes. Extracted from the retired P5 rule
evaluator. Ops are a whitelist — no eval/SSTI."""

# clause op whitelist
OPS = {
    'eq': lambda a, b: a == b,
    'ne': lambda a, b: a != b,
    'gt': lambda a, b: _num(a) > _num(b),
    'gte': lambda a, b: _num(a) >= _num(b),
    'lt': lambda a, b: _num(a) < _num(b),
    'lte': lambda a, b: _num(a) <= _num(b),
    'in': lambda a, b: a in (b or []),
    'not_in': lambda a, b: a not in (b or []),
}


def match_clause(clause: dict, trig) -> bool:
    field = clause.get('field')
    op = OPS.get(clause.get('op'))
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


def _num(v):
    return float(v) if v is not None else 0.0
