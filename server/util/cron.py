"""Minimal 5-field cron matcher (PLAN P5 §6.1 schedule trigger). Supports *, lists (a,b),
ranges (a-b), and steps (*/n, a-b/n). Minute resolution — schedule_trigger beats every minute.
Fields: minute hour day-of-month month day-of-week (dow 0/7=Sun, 1=Mon..6=Sat)."""
_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def _field_set(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(','):
        step = 1
        if '/' in part:
            part, step_s = part.split('/', 1)
            step = int(step_s)
        if part == '*':
            start, end = lo, hi
        elif '-' in part:
            a, b = part.split('-', 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        out.update(range(start, end + 1, step))
    return out


def cron_match(expr: str, dt) -> bool:
    """True if the cron expression matches datetime dt (in its own tz)."""
    try:
        fields = expr.split()
        if len(fields) != 5:
            return False
        dow = dt.isoweekday() % 7        # 0=Sun, 1=Mon..6=Sat
        values = [dt.minute, dt.hour, dt.day, dt.month, dow]
        for i, (field, value) in enumerate(zip(fields, values)):
            lo, hi = _RANGES[i]
            allowed = _field_set(field, lo, hi)
            if i == 4 and 7 in allowed:   # 7 == Sunday alias
                allowed.add(0)
            if value not in allowed:
                return False
        return True
    except (ValueError, AttributeError):
        return False
