"""Scan-based segment indexer (PLAN P2 §6.3 option A+B).

ffmpeg writes flat segments to {disk}/{camera_id}/seg-<UTC ts>.mp4. This scans that
dir for *settled* files (the newest one is still being written), probes each with
ffprobe, and inserts a `segments` row. Scan-based (not inotify) is robust across
bind/network mounts; the recorder calls it each tick.
"""
import logging
import os
import re
from datetime import datetime, timedelta

from server.model import UTC, utcnow
from server.model.segment import REASON_CONTINUOUS, TIER_CACHE, Segment
from server.service import ffmpeg

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r'seg-(\d{8})-(\d{6})\.(mp4|ts)$')
SETTLE_SECONDS = 3


def parse_start_ts(filename: str) -> datetime | None:
    """seg-YYYYMMDD-HHMMSS.ext → naive UTC datetime (container TZ=UTC)."""
    m = _NAME_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
    except ValueError:
        return None


def index_camera_dir(camera_id: int, disk, container: str = 'fmp4',
                     subdir: str = '', stream_role: str = 'main',
                     include_newest: bool = False) -> int:
    """Index settled segment files in {disk}/{camera_id}/[subdir]. Returns count inserted.
    P6 R4: subdir='sub'+stream_role='sub' indexes the dual-recording sub stream.
    include_newest=True is the final flush after the recorder process has exited — the
    last file is no longer being written, so it is indexed too (settle check skipped)."""
    output_dir = os.path.join(disk.mount_path, str(camera_id), subdir) if subdir \
        else os.path.join(disk.mount_path, str(camera_id))
    if not os.path.isdir(output_dir):
        return 0

    ext = ffmpeg.segment_ext(container)
    try:
        files = sorted(f for f in os.listdir(output_dir) if f.endswith('.' + ext) and _NAME_RE.search(f))
    except OSError:
        return 0
    if not include_newest:
        if len(files) <= 1:
            return 0  # newest is in-progress; need ≥2 to have a settled one
        files = files[:-1]  # skip the newest (being written)

    now = utcnow()
    settle_before = now - timedelta(seconds=SETTLE_SECONDS)
    inserted = 0

    for filename in files:
        rel_path = '%s/%s/%s' % (camera_id, subdir, filename) if subdir else '%s/%s' % (camera_id, filename)
        if Segment.exists_rel_path(camera_id, rel_path):
            continue
        abs_path = os.path.join(output_dir, filename)
        try:
            stat = os.stat(abs_path)
        except OSError:
            continue
        # mtime settled? (naive UTC, matching the rest of the index)
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC).replace(tzinfo=None)
        if not include_newest and mtime > settle_before:
            continue

        start_ts = parse_start_ts(filename)
        if start_ts is None:
            continue
        meta = ffmpeg.probe(abs_path) or {}
        duration_ms = meta.get('duration_ms') or 0
        # ffmpeg's -segment_atclocktime keeps rolling files even with no input (e.g. the
        # source 404s) → zero-byte/unprobeable files. Index them as corrupt so playback,
        # HLS and export (which filter corrupt) never see them, while retention still
        # cleans up both the row and the file.
        corrupt = stat.st_size == 0 or duration_ms == 0
        end_ts = start_ts + timedelta(milliseconds=duration_ms) if duration_ms else start_ts

        Segment.create(
            camera_id=camera_id, disk_id=disk.id, rel_path=rel_path,
            start_ts=start_ts, end_ts=end_ts, duration_ms=duration_ms,
            size_bytes=stat.st_size, container=container,
            video_codec=meta.get('video_codec'), has_audio=bool(meta.get('has_audio')),
            width=meta.get('width'), height=meta.get('height'),
            first_keyframe_ms=0, reason=REASON_CONTINUOUS, storage_tier=TIER_CACHE,
            stream_role=stream_role, corrupt=corrupt)
        if not corrupt:
            inserted += 1

    return inserted
