"""Retention / rotation (PLAN P2 §6.9). Days AND capacity AND disk-free; protected
(manual/event) segments are never deleted. Delete order: file unlink → DB row."""
import logging
import os
from datetime import timedelta

import config
from server.model import db, utcnow
from server.model.camera import Camera
from server.model.disk import Disk
from server.model.recording import Recording
from server.model.segment import Segment
from server.model.storage_policy import OVER_DELETE_OLDEST, OVER_STOP, OVER_WARN, RECORD_OFF, StoragePolicy
from server.service import storage_manager
from server.service.reconcile import publish_reconcile

logger = logging.getLogger(__name__)
HARD_MARGIN = config.MIN_WRITE_HEADROOM_BYTES


def _overlaps(seg: Segment, intervals: list) -> bool:
    for start, end in intervals:
        if seg.start_ts < end and seg.end_ts > start:
            return True
    return False


def delete_segment(seg: Segment, disk_map: dict):
    disk = disk_map.get(seg.disk_id)
    if disk:
        path = storage_manager.abs_path(disk, seg.rel_path)
        try:
            os.unlink(path)            # file first, then DB (orphan index < orphan file)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning('unlink failed %s: %s', path, e)
    seg.delete_row()


def free_space(disk: Disk, target_free_bytes: int, disk_map: dict, protected_cache: dict) -> int:
    """Evict oldest unprotected segments on `disk` until estimated free >= target."""
    est_free = disk.free_bytes or 0
    deleted = 0
    for seg in Segment.oldest_on_disk(disk.id, limit=2000):
        if est_free >= target_free_bytes:
            break
        protected = protected_cache.setdefault(seg.camera_id, Recording.get_protected_intervals(seg.camera_id))
        if _overlaps(seg, protected):
            continue
        size = seg.size_bytes or 0
        delete_segment(seg, disk_map)
        est_free += size
        deleted += 1
    db.session.commit()
    disk.refresh_usage()
    return deleted


def _effective_policies() -> list[tuple[int, StoragePolicy]]:
    out = []
    for cam in Camera.get_all_enabled():
        pol = StoragePolicy.get_for_camera(cam.id)
        if pol:
            out.append((cam.id, pol))
    return out


def run_retention() -> dict:
    disk_map = {d.id: d for d in Disk.get_all()}
    protected_cache: dict[int, list] = {}
    deleted_days = deleted_capacity = deleted_diskfree = 0
    warnings: list[str] = []

    # 1) per-camera days-based
    for cam_id, pol in _effective_policies():
        if not pol.retention_days:
            continue
        protected = protected_cache.setdefault(cam_id, Recording.get_protected_intervals(cam_id))
        cutoff = utcnow() - timedelta(days=pol.retention_days)
        for seg in Segment.older_than(cam_id, cutoff, limit=2000):
            if not _overlaps(seg, protected):
                delete_segment(seg, disk_map)
                deleted_days += 1
        db.session.commit()

    # 2) per-camera capacity
    for cam_id, pol in _effective_policies():
        if not pol.retention_max_bytes:
            continue
        used = Segment.total_size_for_camera(cam_id)
        if used <= pol.retention_max_bytes:
            continue
        if pol.over_capacity_policy == OVER_DELETE_OLDEST:
            # retention_max_bytes is a HARD cap. Evict oldest UNPROTECTED segments first (keep
            # event clips while there's other data to drop); if the camera is still over the cap
            # because almost everything is event-protected, evict the oldest protected (event)
            # clips too — otherwise a camera that fires events constantly would grow without
            # bound and silently ignore its configured size limit.
            protected = protected_cache.setdefault(cam_id, Recording.get_protected_intervals(cam_id))
            segs = Segment.oldest_for_camera(cam_id, limit=5000)
            deleted_ids: set = set()
            for allow_protected in (False, True):
                for seg in segs:
                    if used <= pol.retention_max_bytes:
                        break
                    if seg.id in deleted_ids:
                        continue
                    if not allow_protected and _overlaps(seg, protected):
                        continue
                    used -= (seg.size_bytes or 0)
                    delete_segment(seg, disk_map)
                    deleted_ids.add(seg.id)
                    deleted_capacity += 1
                if used <= pol.retention_max_bytes:
                    break
            db.session.commit()
        elif pol.over_capacity_policy == OVER_STOP:
            row = StoragePolicy.get_raw_for_camera(cam_id)
            if row is None:
                # camera inherits the shared global policy object — flipping it off
                # would stop recording for every camera; materialize a per-camera
                # override (copying the inherited fields) and stop only this one.
                row = StoragePolicy()
                row.camera_id = cam_id
                for key in ('segment_seconds', 'container', 'balance_strategy', 'pinned_disk_id',
                            'retention_days', 'retention_max_bytes', 'over_capacity_policy',
                            'cache_buffer_seconds', 'event_retention_days'):
                    setattr(row, key, getattr(pol, key))
            row.record_mode = RECORD_OFF
            db.session.add(row)
            db.session.commit()
            publish_reconcile(cam_id, 'mode_change')
            warnings.append('capacity_full_stopped:%s' % cam_id)
        elif pol.over_capacity_policy == OVER_WARN:
            warnings.append('capacity_exceeded:%s' % cam_id)

    # 3) disk free-space watchdog
    for disk in storage_manager.disks_needing_rotation():
        target = (disk.reserved_free_bytes or 0) + HARD_MARGIN
        freed = free_space(disk, target, disk_map, protected_cache)
        deleted_diskfree += freed
        if freed == 0 and (disk.free_bytes or 0) <= (disk.reserved_free_bytes or 0):
            warnings.append('no_evictable_space:%s' % disk.name)

    return {'deleted_days': deleted_days, 'deleted_capacity': deleted_capacity,
            'deleted_diskfree': deleted_diskfree, 'warnings': warnings}


def check_pool_overcommit(proposed: dict | None = None) -> list[str]:
    """Warn if Σ(per-camera retention_max_bytes) + reserved exceeds the record pool."""
    warnings = []
    disks = Disk.get_writable()
    pool_total = sum((d.total_bytes or 0) for d in disks)
    reserved = sum((d.reserved_free_bytes or 0) for d in disks)
    committed = 0
    for _, pol in _effective_policies():
        if pol.retention_max_bytes:
            committed += pol.retention_max_bytes
    if proposed and proposed.get('retention_max_bytes'):
        committed += proposed['retention_max_bytes']
    if committed + reserved > pool_total and pool_total > 0:
        warnings.append('pool_overcommit')
    return warnings
