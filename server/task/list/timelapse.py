"""Timelapse generation (PLAN §7.5). Concat the range's segments → setpts/fps
downsample → H.264. Progress via ffmpeg -progress."""
import logging
import os
import subprocess

import sentry_sdk

from server.model import utcnow
from server.model.disk import Disk
from server.model.segment import Segment
from server.model.timelapse_job import (
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TimelapseJob,
)
from server.service import ffmpeg, storage_manager
from server.task.celery import app, celery_use_db
from server.task.list.transcode import _parse_out_time

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.timelapse.run_timelapse')
@celery_use_db()
def run_timelapse(job_id):
    job = TimelapseJob.get_by_id(int(job_id))
    if not job:
        return
    if job.status == STATUS_CANCELED:          # canceled while queued/waiting
        return

    # Future range — capture-forward timelapse: defer generation until the period has
    # elapsed (re-queue). Recordings accumulate per the schedule in the meantime.
    now = utcnow()
    if job.range_end_ts > now:
        remaining = (job.range_end_ts - now).total_seconds()
        run_timelapse.apply_async((str(job.id),), countdown=min(max(5.0, remaining), 3600.0))
        job.update(status=STATUS_QUEUED, progress=0)
        return

    job.update(status=STATUS_RUNNING, progress=0)
    try:
        segments = Segment.get_range(job.camera_id, job.range_start_ts, job.range_end_ts)
        if not segments:
            job.update(status=STATUS_FAILED, error='no_segments')
            return

        disk = storage_manager.pick_write_disk(job.camera_id, None) or next(iter(Disk.get_writable()), None)
        if disk is None:
            job.update(status=STATUS_FAILED, error='no_output_disk')
            return

        out_rel = 'timelapse/%s/timelapse.mp4' % job.id
        out_abs = storage_manager.abs_path(disk, out_rel)
        os.makedirs(os.path.dirname(out_abs), exist_ok=True)
        list_file = storage_manager.abs_path(disk, 'timelapse/%s/list.txt' % job.id)
        with open(list_file, 'w') as f:
            for seg in segments:
                seg_disk = Disk.get_by_id(seg.disk_id)
                if not seg_disk:
                    continue
                seg_abs = storage_manager.abs_path(seg_disk, seg.rel_path)
                if os.path.exists(seg_abs):
                    f.write("file '%s'\n" % seg_abs.replace("'", "'\\''"))

        source_seconds = max(1.0, (job.range_end_ts - job.range_start_ts).total_seconds())
        params = job.params or {}
        cmd = ffmpeg.build_timelapse_cmd(list_file, out_abs, job.speed_factor, params.get('fps', 30))

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        last = 0
        for line in proc.stdout:
            seconds = _parse_out_time(line)
            if seconds is not None:
                pct = min(99, int(seconds * job.speed_factor / source_seconds * 100))
                if pct >= last + 5:
                    last = pct
                    job.update(progress=pct)
        proc.wait()

        if proc.returncode != 0 or not os.path.exists(out_abs):
            job.update(status=STATUS_FAILED, error='ffmpeg_failed')
            return
        try:
            os.unlink(list_file)
        except OSError:
            pass
        job.update(status=STATUS_DONE, progress=100, output_disk_id=disk.id,
                   output_path=out_rel, output_size=os.path.getsize(out_abs))
        logger.info('timelapse %s done', job.id)
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception('timelapse %s failed', job_id)
        job.update(status=STATUS_FAILED, error=str(e)[:512])
