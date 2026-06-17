"""Pre/post event buffer recovery (PLAN P2 §6.6). The cache disk's rolling segments
ARE the pre-buffer, so 'the last N seconds' already exist as files. P3 calls retain()
to protect [event_ts-pre, event_ts+post]; this Phase implements + tests the mechanism.
"""
from datetime import timedelta

from server.model import db
from server.model.recording import CLASS_EVENT, CLASS_PROTECTED, Recording
from server.model.segment import REASON_MANUAL, Segment


def retain(camera_id: int, event_ts, pre_seconds: int = 10, post_seconds: int = 10,
           reason: str = 'event', created_by_id=None, note: str | None = None) -> Recording:
    """Create a protected recording over [event_ts-pre, event_ts+post] and mark its
    segments so rotation skips them. Post is future → confirmed once recorded."""
    start = event_ts - timedelta(seconds=pre_seconds)
    end = event_ts + timedelta(seconds=post_seconds)
    retention_class = CLASS_EVENT if reason == 'event' else CLASS_PROTECTED
    recording = Recording.create(camera_id, reason, retention_class, start, end, created_by_id, note)
    _protect_segments(camera_id, start, end)
    return recording


def _protect_segments(camera_id: int, start, end):
    for seg in Segment.get_range(camera_id, start, end):
        seg.mark_reason(REASON_MANUAL)
    db.session.commit()
