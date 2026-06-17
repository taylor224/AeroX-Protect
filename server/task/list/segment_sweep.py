"""Cache→record promotion, orphan-index cleanup, disk evacuation (PLAN P2 §6.5, §6.9)."""
import logging
import os
import shutil
from datetime import timedelta

from server.model import db, utcnow
from server.model.disk import ROLE_RECORD, Disk
from server.model.segment import TIER_RECORD, Segment
from server.model.storage_policy import StoragePolicy
from server.service import storage_manager
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


def _move_segment(seg: Segment, src_disk: Disk, dst_disk: Disk):
    src = storage_manager.abs_path(src_disk, seg.rel_path)
    dst = storage_manager.abs_path(dst_disk, seg.rel_path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    seg.disk_id = dst_disk.id
    seg.storage_tier = TIER_RECORD
    db.session.add(seg)


@app.task(name='server.task.list.segment_sweep.sweep')
@celery_use_db()
def sweep():
    """Promote settled cache segments to record disks; prune orphan index rows."""
    disk_map = {d.id: d for d in Disk.get_all()}
    record_disks = sorted([d for d in Disk.get_writable((ROLE_RECORD,))],
                          key=lambda d: d.usable_free_bytes, reverse=True)

    global_pol = StoragePolicy.get_global()
    cache_buffer = (global_pol.cache_buffer_seconds if global_pol else 60) or 60
    cutoff = utcnow() - timedelta(seconds=cache_buffer)

    promoted = 0
    for seg in Segment.cache_tier_older_than(cutoff, limit=500):
        src = disk_map.get(seg.disk_id)
        if src is None:
            continue
        if record_disks and src.role != ROLE_RECORD:
            dst = record_disks[0]
            try:
                _move_segment(seg, src, dst)
                promoted += 1
            except OSError as e:
                logger.warning('promote failed for seg %s: %s', seg.id, e)
        else:
            seg.storage_tier = TIER_RECORD   # single-disk: promote in place
            db.session.add(seg)
    db.session.commit()

    # orphan index rows: only rows whose disk row is GONE entirely. Soft-deleted
    # (unregistered) disks keep their segment index — the media may come back.
    known_disk_ids = {row[0] for row in db.session.query(Disk.id).all()}
    orphans = 0
    if known_disk_ids:
        orphan_rows = db.session.query(Segment).filter(
            Segment.disk_id.notin_(known_disk_ids)).limit(2000).all()
        for seg in orphan_rows:
            db.session.delete(seg)
            orphans += 1
        db.session.commit()

    if promoted or orphans:
        logger.info('segment_sweep: promoted=%d orphans=%d', promoted, orphans)
    return {'promoted': promoted, 'orphans': orphans}


@app.task(name='server.task.list.segment_sweep.evacuate_disk')
@celery_use_db()
def evacuate_disk(disk_id):
    """Move all segments off a disk before removal."""
    disk_id = int(disk_id)
    targets = [d for d in Disk.get_writable() if d.id != disk_id]
    if not targets:
        logger.warning('evacuate_disk %s: no target disks', disk_id)
        return {'moved': 0, 'error': 'no_targets'}
    src = db.session.query(Disk).filter(Disk.id == disk_id).first()
    if not src:
        return {'moved': 0, 'error': 'not_found'}
    moved = 0
    failed_ids: set[int] = set()
    while True:
        batch = [s for s in Segment.oldest_on_disk(disk_id, limit=200 + len(failed_ids))
                 if s.id not in failed_ids]
        if not batch:
            break
        for seg in batch:
            dst = max(targets, key=lambda d: d.usable_free_bytes)
            try:
                _move_segment(seg, src, dst)
                moved += 1
            except OSError as e:
                # keep the row — the file is still on the source disk; deleting the
                # index here would orphan the file and lose the recording.
                logger.warning('evacuate move failed seg %s: %s', seg.id, e)
                failed_ids.add(seg.id)
        db.session.commit()
    logger.info('evacuate_disk %s: moved %d segments, %d failed', disk_id, moved, len(failed_ids))
    return {'moved': moved, 'failed': len(failed_ids)}
