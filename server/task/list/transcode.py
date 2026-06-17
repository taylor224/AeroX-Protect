"""Clip export: concat copy / H.264 transcode with progress (PLAN P2 §7.4)."""
import logging
import os
import subprocess

import sentry_sdk

from server.model import utcnow
from server.model.disk import Disk
from server.model.export_job import (
    MODE_COPY,
    STATUS_DONE,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    ExportJob,
)
from server.model.segment import Segment
from server.service import ffmpeg, storage_manager
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


def _parse_out_time(line: str) -> float | None:
    """ffmpeg -progress 'out_time=HH:MM:SS.micro' → seconds."""
    if not line.startswith('out_time='):
        return None
    value = line.split('=', 1)[1].strip()
    try:
        h, m, s = value.split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, IndexError):
        return None


def _zip_with_password(src_abs: str, zip_abs: str, password: str):
    """AES-256 password-protected zip (PLAN P6 R3). pyzipper writes WinZip-AES, openable by
    any standard unzip with the password."""
    import pyzipper
    with pyzipper.AESZipFile(zip_abs, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword((password or '').encode())
        zf.write(src_abs, arcname=os.path.basename(src_abs))


@app.task(name='server.task.list.transcode.run_export_job')
@celery_use_db()
def run_export_job(job_id):
    job = ExportJob.get_by_id(int(job_id))
    if not job:
        return
    job.update(status=STATUS_PROCESSING, progress=0)
    try:
        segments = Segment.get_range(job.camera_id, job.start_ts, job.end_ts)
        if not segments:
            job.update(status=STATUS_FAILED, error_message='no_segments')
            return

        disk = storage_manager.pick_write_disk(job.camera_id, None)
        if disk is None:
            disk = next(iter(Disk.get_writable()), None)
        if disk is None:
            job.update(status=STATUS_FAILED, error_message='no_output_disk')
            return

        out_dir_rel = 'exports/%s' % job.id
        out_rel = '%s/clip.%s' % (out_dir_rel, job.container)
        out_abs = storage_manager.abs_path(disk, out_rel)
        os.makedirs(os.path.dirname(out_abs), exist_ok=True)

        list_file = storage_manager.abs_path(disk, '%s/list.txt' % out_dir_rel)
        included = []
        with open(list_file, 'w') as f:
            for seg in segments:
                seg_disk = Disk.get_by_id(seg.disk_id)
                if not seg_disk:
                    continue
                seg_abs = storage_manager.abs_path(seg_disk, seg.rel_path)
                if os.path.exists(seg_abs) and os.path.getsize(seg_abs) > 0:
                    f.write("file '%s'\n" % seg_abs.replace("'", "'\\''"))
                    included.append(seg)

        if not included:
            job.update(status=STATUS_FAILED, error_message='no_segments_on_disk')
            return
        # trim offsets are relative to the concat timeline, which is GAPLESS — segment
        # durations summed, recording gaps collapsed. Walking the included segments and
        # accumulating media time keeps the offsets correct when the requested window
        # spans a gap (camera offline / schedule off); a plain wall-clock delta from the
        # first segment would overshoot by the gap length.
        acc = 0.0
        start_trim = None
        end_trim = 0.0
        for seg in included:
            seg_dur = max(0.0, (seg.end_ts - seg.start_ts).total_seconds())
            if start_trim is None and seg.end_ts > job.start_ts:
                start_trim = acc + max(0.0, (job.start_ts - seg.start_ts).total_seconds())
            if seg.start_ts < job.end_ts:
                end_trim = acc + min(seg_dur, (job.end_ts - seg.start_ts).total_seconds())
            acc += seg_dur
        start_trim = start_trim or 0.0
        total_seconds = max(1.0, end_trim - start_trim)

        if job.mode == MODE_COPY:
            cmd = ffmpeg.build_concat_copy_cmd(list_file, out_abs, start_trim, end_trim)
        elif job.watermark:
            cmd = ffmpeg.build_watermark_transcode_cmd(
                list_file, out_abs, start_trim, end_trim,
                ffmpeg.preset_height(job.transcode_preset), job.watermark_text)
        else:
            cmd = ffmpeg.build_transcode_cmd(list_file, out_abs, start_trim, end_trim,
                                             ffmpeg.preset_height(job.transcode_preset))

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        last_pct = 0
        for line in proc.stdout:
            seconds = _parse_out_time(line)
            if seconds is not None:
                pct = min(99, int(seconds / total_seconds * 100))
                if pct >= last_pct + 5:
                    last_pct = pct
                    job.update(progress=pct)
        proc.wait()

        if proc.returncode != 0 or not os.path.exists(out_abs):
            job.update(status=STATUS_FAILED, error_message='ffmpeg_failed')
            return
        try:
            os.unlink(list_file)
        except OSError:
            pass

        # P6 R3 — wrap the clip in an AES-encrypted, password-protected zip.
        final_abs, final_rel = out_abs, out_rel
        if job.password_protected and job.enc_password:
            from server.util.crypto import decrypt_credential
            password = decrypt_credential(job.enc_password, job.enc_key_id)
            zip_rel = '%s/clip.zip' % out_dir_rel
            zip_abs = storage_manager.abs_path(disk, zip_rel)
            _zip_with_password(out_abs, zip_abs, password or '')
            try:
                os.unlink(out_abs)
            except OSError:
                pass
            final_abs, final_rel = zip_abs, zip_rel

        job.update(status=STATUS_DONE, progress=100, output_disk_id=disk.id,
                   output_rel_path=final_rel, output_size_bytes=os.path.getsize(final_abs))
        logger.info('export %s done (%d bytes)', job.id, os.path.getsize(final_abs))
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception('export %s failed', job_id)
        job.update(status=STATUS_FAILED, error_message=str(e)[:1000])


@app.task(name='server.task.list.transcode.expire_export_jobs')
@celery_use_db()
def expire_export_jobs():
    """Hourly: delete expired export outputs + mark expired."""
    from server.controller.export import ExportController
    count = 0
    for job in ExportJob.get_expired(utcnow()):
        ExportController._cleanup_output(job)
        job.update(status=STATUS_EXPIRED)
        count += 1
    if count:
        logger.info('expire_export_jobs: %d cleaned', count)
    return count
