"""Edge-recording import service (PLAN P6 R6). Gap-fills the NVR timeline from a camera's
on-board SD clips: find the *gaps* in our `segments` over a range, ask the camera driver
for its SD clips, download only the clips that overlap a gap, and index them as
`reason='edge'` segments (+ an `edge` Recording spanning the import). Runs in Celery
(network/disk I/O). The driver layer (`server.driver.edge`) is mocked in tests; the gap
math + import bookkeeping here is the unit-tested core.
"""
import logging
import os
from datetime import datetime, timedelta

from server.model import db, to_epoch_ms, utcnow
from server.model.camera import Camera
from server.model.edge_import_job import (
    STATUS_DONE, STATUS_FAILED, STATUS_QUEUED, STATUS_RUNNING, EdgeImportJob,
)
from server.model.recording import CLASS_DEFAULT, REASON_EDGE as REC_REASON_EDGE, Recording
from server.model.segment import REASON_EDGE, TIER_RECORD, Segment
from server.service import storage_manager

logger = logging.getLogger(__name__)

MIN_GAP_SECONDS = 2          # ignore sub-2s slivers between adjacent segments


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping/adjacent intervals (sorted by start)."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def compute_gaps(camera_id: int, start: datetime, end: datetime,
                 min_gap_s: int = MIN_GAP_SECONDS) -> list[tuple[datetime, datetime]]:
    """Uncovered sub-intervals of [start, end] not spanned by any existing segment."""
    if end <= start:
        return []
    segs = Segment.get_range(camera_id, start, end)
    covered = _merge([(max(s.start_ts, start), min(s.end_ts, end)) for s in segs])

    gaps, cursor = [], start
    for cs, ce in covered:
        if cs > cursor:
            gaps.append((cursor, cs))
        cursor = max(cursor, ce)
    if cursor < end:
        gaps.append((cursor, end))
    return [(a, b) for a, b in gaps if (b - a).total_seconds() >= min_gap_s]


def gaps_preview(camera_id: int, start: datetime, end: datetime) -> list[dict]:
    return [{'start_ts': to_epoch_ms(a), 'end_ts': to_epoch_ms(b),
             'duration_ms': int((b - a).total_seconds() * 1000)}
            for a, b in compute_gaps(camera_id, start, end)]


AUTO_WINDOW_HOURS = 6        # how far back each auto-scan looks for fresh gaps to backfill


def auto_import_due() -> int:
    """For every camera with `edge_recording` AND `edge_auto_import`, queue an import of any
    timeline gaps in the recent window. Idempotent: imported clips become `edge` segments that
    cover the gap, so a later scan won't re-import them. Skips cameras with no gaps or one that
    already has an active job (so scans never pile up). Returns the number of jobs queued."""
    from server.task.list.edge_import import run_edge_import

    now = utcnow()
    start = now - timedelta(hours=AUTO_WINDOW_HOURS)
    queued = 0
    cams = db.session.query(Camera).filter(
        Camera.deleted_at.is_(None), Camera.is_enabled.is_(True),
        Camera.edge_recording.is_(True), Camera.edge_auto_import.is_(True)).all()
    for cam in cams:
        active = db.session.query(EdgeImportJob).filter(
            EdgeImportJob.camera_id == cam.id,
            EdgeImportJob.status.in_([STATUS_QUEUED, STATUS_RUNNING])).first()
        if active or not compute_gaps(cam.id, start, now):
            continue
        job = EdgeImportJob.create(cam.id, start, now, actor_id=None)
        run_edge_import.delay(job.id)
        queued += 1
    return queued


def run_import(job_id: int):
    from server.driver import edge as edge_drv

    job = EdgeImportJob.get_by_id(job_id)
    if not job:
        return
    camera = db.session.query(Camera).filter(Camera.id == job.camera_id, Camera.deleted_at.is_(None)).first()
    if not camera:
        job.update(status=STATUS_FAILED, error_message='camera_not_found')
        return

    job.update(status=STATUS_RUNNING, progress=0)
    gaps = compute_gaps(camera.id, job.range_start, job.range_end)
    if not gaps:
        job.update(status=STATUS_DONE, progress=100, clips_found=0, clips_imported=0,
                   manifest=[], error_message=None)
        return

    try:
        clips = edge_drv.search_clips(camera, job.range_start, job.range_end)
    except Exception as e:                                    # driver/network/vendor failure
        logger.warning('edge search failed camera=%s: %s', camera.id, e)
        job.update(status=STATUS_FAILED, error_message='search_failed: %s' % e)
        return

    to_import = [c for c in clips if any(c.overlaps(a, b) for a, b in gaps)]
    job.update(clips_found=len(clips))
    if not to_import:
        job.update(status=STATUS_DONE, progress=100, clips_imported=0, manifest=[])
        return

    disk = storage_manager.pick_write_disk(camera.id, None)
    if disk is None:
        job.update(status=STATUS_FAILED, error_message='no_writable_disk')
        return
    edge_dir = os.path.join(disk.mount_path, str(camera.id), 'edge')
    os.makedirs(edge_dir, exist_ok=True)

    manifest, bytes_done, imported = [], 0, 0
    for idx, clip in enumerate(to_import):
        filename = 'edge-%d.mp4' % to_epoch_ms(clip.start_ts)
        rel_path = '%s/edge/%s' % (camera.id, filename)
        if Segment.exists_rel_path(camera.id, rel_path):
            continue        # same start_ts already imported by an earlier job — idempotent skip
        dest_abs = os.path.join(edge_dir, filename)
        try:
            size = edge_drv.download_clip(camera, clip, dest_abs)
        except Exception as e:
            logger.warning('edge clip download failed camera=%s uri=%s: %s', camera.id, clip.uri, e)
            continue

        duration_ms = int((clip.end_ts - clip.start_ts).total_seconds() * 1000)
        Segment.create(
            camera_id=camera.id, disk_id=disk.id, rel_path=rel_path,
            start_ts=clip.start_ts, end_ts=clip.end_ts, duration_ms=duration_ms,
            size_bytes=size, container='fmp4', video_codec=None, has_audio=False,
            first_keyframe_ms=0, reason=REASON_EDGE, storage_tier=TIER_RECORD, stream_role='main')
        imported += 1
        bytes_done += size
        manifest.append({'start_ts': to_epoch_ms(clip.start_ts), 'end_ts': to_epoch_ms(clip.end_ts),
                         'size_bytes': size, 'rel_path': rel_path})
        job.update(progress=int(idx * 100 / len(to_import)), clips_imported=imported, bytes_done=bytes_done)

    if imported:
        span_start = min(c.start_ts for c in to_import)
        span_end = max(c.end_ts for c in to_import)
        Recording.create(camera_id=camera.id, reason=REC_REASON_EDGE, retention_class=CLASS_DEFAULT,
                         start_ts=span_start, end_ts=span_end, note='edge import')

    job.update(status=STATUS_DONE, progress=100, clips_imported=imported,
               bytes_done=bytes_done, manifest=manifest, error_message=None)
    return job
