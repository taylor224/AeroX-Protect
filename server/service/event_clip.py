"""Event clip materialization (PLAN §5.6, §7.2). Pre/post-buffer recovery from the
P2 cache — NO re-encode: an event Recording over [start-pre, end+post] protects the
existing segments (retention_engine skips protected/event recordings). Overlapping
event recordings are coalesced (extended)."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.event import Event
from server.model.recording import CLASS_EVENT, REASON_EVENT, Recording
from server.model.storage_policy import StoragePolicy

logger = logging.getLogger(__name__)


def materialize(event_id: int, pre_s: int, post_s: int, retention_class: str | None = None) -> Recording | None:
    ev = Event.get_by_id(event_id)
    if not ev:
        return None

    # clamp pre-buffer to the cache retention (can't recover beyond what's on disk)
    policy = StoragePolicy.get_for_camera(ev.camera_id)
    cache_seconds = (policy.cache_buffer_seconds if policy else 60) or 60
    pre_s = min(pre_s, cache_seconds)

    start = ev.start_ts - timedelta(seconds=pre_s)
    end = (ev.end_ts or utcnow()) + timedelta(seconds=post_s)

    existing = Recording.find_overlapping(ev.camera_id, start, end, REASON_EVENT)
    if existing:
        existing.extend(start, end)
        rec = existing
    else:
        rec = Recording.create(
            camera_id=ev.camera_id, reason=REASON_EVENT, retention_class=CLASS_EVENT,
            start_ts=start, end_ts=end, note='event:%s' % ev.type)

    ev.recording_id = rec.id
    from server.model import db
    db.session.add(ev)
    db.session.commit()
    logger.info('event %s → recording %s [%s..%s]', ev.id, rec.id, start, end)
    return rec
