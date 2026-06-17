"""Warm segment thumbnails for fast timeline hover (PLAN P2 §7.3). The /thumb
endpoint also generates on demand; this just pre-warms the latest per camera."""
import logging
import os
import subprocess

import config
from server.model.camera import Camera
from server.model.disk import Disk
from server.model.segment import Segment
from server.service import ffmpeg, storage_manager
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.thumbnail.backfill_thumbnails')
@celery_use_db()
def backfill_thumbnails():
    from server.model import db
    from server.service.token import get_redis
    redis = get_redis()
    count = 0
    for cam in Camera.get_all_enabled():
        seg = (db.session.query(Segment).filter(Segment.camera_id == cam.id, Segment.corrupt.is_(False))
               .order_by(Segment.start_ts.desc()).first())
        if not seg:
            continue
        key = '%ssegthumb:%s' % (config.THUMB_CACHE_PREFIX, seg.id)
        try:
            if redis.exists(key):
                continue
        except Exception:
            pass
        disk = Disk.get_by_id(seg.disk_id)
        if not disk:
            continue
        path = storage_manager.abs_path(disk, seg.rel_path)
        if not os.path.exists(path):
            continue
        try:
            out = subprocess.run(ffmpeg.build_frame_cmd(path, 0.0), capture_output=True, timeout=15)
            if out.returncode == 0 and out.stdout:
                redis.setex(key, 3600, out.stdout)
                count += 1
        except (subprocess.SubprocessError, OSError, Exception):
            continue
    if count:
        logger.info('backfill_thumbnails: warmed %d', count)
    return count
