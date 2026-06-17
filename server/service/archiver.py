"""Archiver (PLAN P6 M2). Offloads a recording's segments to an archive target, writing a
manifest (restore index) onto the job. Runs in Celery (heavy I/O). Each segment is uploaded
via the type-specific driver; failures fail the job with a reason.
"""
import logging
import os

from server.model import db, to_epoch_ms
from server.model.archive_job import STATUS_DONE, STATUS_FAILED, STATUS_RUNNING, ArchiveJob
from server.model.archive_target import ArchiveTarget
from server.model.disk import Disk
from server.model.recording import Recording
from server.model.segment import Segment
from server.service import storage_manager

logger = logging.getLogger(__name__)


def run(job_id: int):
    job = ArchiveJob.get_by_id(job_id)
    if not job:
        return
    target = ArchiveTarget.get_by_id(job.target_id)
    if not target or not target.enabled or target.deleted_at is not None:
        job.update(status=STATUS_FAILED, error_message='target_unavailable')
        return
    rec = db.session.query(Recording).filter(Recording.id == int(job.source_ref)).first()
    if not rec:
        job.update(status=STATUS_FAILED, error_message='recording_not_found')
        return

    segments = Segment.get_range(rec.camera_id, rec.start_ts, rec.end_ts or rec.start_ts)
    if not segments:
        job.update(status=STATUS_FAILED, error_message='no_segments')
        return

    from server.driver import archive as archive_drv
    prefix = 'recording_%s' % rec.id
    manifest, bytes_done = [], 0
    job.update(status=STATUS_RUNNING, progress=0)
    try:
        for i, seg in enumerate(segments):
            disk = Disk.get_by_id(seg.disk_id)
            if not disk:
                continue
            src = storage_manager.abs_path(disk, seg.rel_path)
            if not os.path.exists(src):
                continue
            ext = 'ts' if seg.container == 'mpegts' else 'mp4'
            remote = '%s/seg_%05d.%s' % (prefix, i, ext)
            n = archive_drv.upload(target, src, remote)
            bytes_done += n
            manifest.append({'segment_id': str(seg.id), 'remote': remote, 'bytes': n,
                             'start_ts': to_epoch_ms(seg.start_ts)})
            job.update(bytes_done=bytes_done, progress=min(99, int((i + 1) / len(segments) * 100)))
        job.update(status=STATUS_DONE, progress=100, bytes_total=bytes_done,
                   manifest={'recording_id': str(rec.id), 'count': len(manifest), 'items': manifest})
        logger.info('archive job %s done (%d files, %d bytes)', job.id, len(manifest), bytes_done)
    except Exception as e:  # noqa: BLE001
        logger.exception('archive job %s failed', job_id)
        job.update(status=STATUS_FAILED, error_message=str(e)[:1000])
