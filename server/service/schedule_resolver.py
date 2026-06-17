"""(camera_id, ts) → recording mode from the weekly schedule (PLAN §7.3).

ts is naive UTC; schedules are interpreted in the configured SITE timezone (Settings →
timezone, default Asia/Seoul; day_of_week 0=Mon, minute-of-day). No rule → continuous."""
import time
from datetime import datetime, timedelta, timezone

from server.model.schedule import MODE_CONTINUOUS, Schedule

_DEFAULT_TZ = 'Asia/Seoul'
_KST = timezone(timedelta(hours=9))                 # ultimate fallback if tzdata is absent
_cache = {'name': None, 'zone': _KST, 'at': 0.0}    # 30s TTL — avoids a DB hit per tick


def _site_zone():
    now = time.time()
    if now - _cache['at'] > 30:
        from server.model.setting import Setting
        name = Setting.get_value('timezone', _DEFAULT_TZ) or _DEFAULT_TZ
        if name != _cache['name']:
            try:
                from zoneinfo import ZoneInfo
                _cache['zone'] = ZoneInfo(name)
            except Exception:
                _cache['zone'] = _KST
            _cache['name'] = name
        _cache['at'] = now
    return _cache['zone']


def mode(camera_id: int, ts_utc: datetime) -> str:
    local = ts_utc.replace(tzinfo=timezone.utc).astimezone(_site_zone())
    dow = local.weekday()                    # Mon=0 .. Sun=6
    minute = local.hour * 60 + local.minute
    rules = Schedule.get_for_camera_dow(camera_id, dow)
    applicable = [r for r in rules if r.start_min <= minute < r.end_min]
    if not applicable:
        return MODE_CONTINUOUS               # default when unscheduled
    return max(applicable, key=lambda r: r.priority).mode
