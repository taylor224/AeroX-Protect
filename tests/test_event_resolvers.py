"""P3 resolver + decision-table unit tests: schedule mode (KST), policy specificity, combine.

Schedules are interpreted in KST; 2026-06-08 is a Monday (dow=0), 2026-06-07 a Sunday (dow=6)."""
from datetime import datetime

from server.model import db
from server.model.event_policy import EventPolicy
from server.model.schedule import (
    MODE_CONTINUOUS,
    MODE_EVENT,
    MODE_MOTION_ONLY,
    MODE_OFF,
    Schedule,
)
from server.service import event_policy_resolver as R
from server.service import schedule_resolver as S
from server.service.event_pipeline import combine

CAM = 7777   # arbitrary camera_id — resolvers only need the id, not a real row


def _rule(dow, start_min, end_min, mode, priority=0):
    r = Schedule()
    r.camera_id = CAM
    r.day_of_week = dow
    r.start_min = start_min
    r.end_min = end_min
    r.mode = mode
    r.priority = priority
    db.session.add(r)
    db.session.commit()
    return r


# ── schedule_resolver (KST, weekly) ───────────────────────────────────────────
def test_schedule_default_continuous(app_db):
    assert S.mode(CAM, datetime(2026, 6, 8, 3, 0)) == MODE_CONTINUOUS   # no rules


def test_schedule_rule_match_and_miss_kst(app_db):
    _rule(0, 540, 1080, MODE_OFF)                                       # Mon 09:00–18:00 KST = off
    assert S.mode(CAM, datetime(2026, 6, 8, 3, 0)) == MODE_OFF          # Mon 12:00 KST (=03:00 UTC) inside
    assert S.mode(CAM, datetime(2026, 6, 7, 23, 0)) == MODE_CONTINUOUS  # Mon 08:00 KST outside → default


def test_schedule_kst_day_rollover(app_db):
    _rule(0, 0, 360, MODE_EVENT)                                        # Mon 00:00–06:00 KST = event
    assert S.mode(CAM, datetime(2026, 6, 7, 20, 0)) == MODE_EVENT       # Sun 20:00 UTC = Mon 05:00 KST
    assert S.mode(CAM, datetime(2026, 6, 7, 14, 0)) == MODE_CONTINUOUS  # Sun 23:00 KST — still Sunday


def test_schedule_priority_wins(app_db):
    _rule(0, 540, 1080, MODE_OFF, priority=0)
    _rule(0, 540, 1080, MODE_MOTION_ONLY, priority=10)
    assert S.mode(CAM, datetime(2026, 6, 8, 3, 0)) == MODE_MOTION_ONLY  # highest priority applicable


# ── event_policy_resolver (specificity) ───────────────────────────────────────
def test_policy_type_beats_wildcard(app_db):
    # seeded global defaults: motion→record, *→notify_only
    assert R.resolve(CAM, 'motion').action == 'record'
    assert R.resolve(CAM, 'tamper').action == 'notify_only'             # only the * policy matches


def test_policy_camera_beats_global(app_db):
    EventPolicy.create({'camera_id': CAM, 'event_type': 'motion', 'action': 'discard'})
    p = R.resolve(CAM, 'motion')
    assert p.action == 'discard' and p.camera_id == CAM


def test_policy_subtype_specific_excludes_others(app_db):
    EventPolicy.create({'camera_id': CAM, 'event_type': 'motion', 'subtype': 'pir', 'action': 'discard'})
    assert R.resolve(CAM, 'motion', 'pir').action == 'discard'          # subtype matches the specific policy
    assert R.resolve(CAM, 'motion', 'vmd').action == 'record'           # excluded → falls back to global


# ── combine decision table (PLAN §5.7) ────────────────────────────────────────
def test_combine_discard_always():
    assert combine('discard', 'continuous', 'motion') == 'discard'
    assert combine('discard', 'off', 'tamper') == 'discard'


def test_combine_record_modes():
    assert combine('record', 'continuous', 'motion') == 'record'
    assert combine('record', 'event', 'tamper') == 'record'
    assert combine('record', 'off', 'motion') == 'discard'
    assert combine('record', 'motion_only', 'tamper') == 'discard'      # non-motion suppressed
    assert combine('record', 'motion_only', 'motion') == 'record'


def test_combine_notify_only():
    assert combine('notify_only', 'continuous', 'tamper') == 'notify_only'
    assert combine('notify_only', 'motion_only', 'tamper') == 'discard'
    assert combine('notify_only', 'motion_only', 'motion') == 'notify_only'


def test_combine_timelapse():
    assert combine('timelapse', 'continuous', 'motion') == 'timelapse'
    assert combine('timelapse', 'off', 'motion') == 'discard'
    assert combine('timelapse', 'motion_only', 'tamper') == 'discard'
