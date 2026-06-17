"""Durable last-frame store for camera tiles. The camera-health pass writes each online
camera's latest JPEG here (atomic temp+rename); the thumbnail endpoint reads it as the
fallback once the short-lived Redis cache expires, so an offline camera still shows its last
known frame indefinitely instead of going blank. Best-effort: filesystem errors never break
the caller. Lives on the shared `/media` volume (backend writes via API, worker via beat)."""
import logging
import os

import config

logger = logging.getLogger(__name__)


def _path(camera_uuid: str) -> str:
    # uuids are hex (no path separators) so this can't traverse
    return os.path.join(config.THUMB_DIR, '%s.jpg' % camera_uuid)


def _is_jpeg(data: bytes | None) -> bool:
    # SOI marker + non-trivial size — never persist/serve a cold-stream garbage blob
    return bool(data) and len(data) >= 512 and data[:2] == b'\xff\xd8'


def save(camera_uuid: str, jpeg: bytes) -> None:
    if not _is_jpeg(jpeg):
        return
    try:
        os.makedirs(config.THUMB_DIR, exist_ok=True)
        path = _path(camera_uuid)
        tmp = '%s.tmp' % path
        with open(tmp, 'wb') as f:
            f.write(jpeg)
        os.replace(tmp, path)            # atomic swap — readers never see a half-written file
    except OSError as e:
        logger.warning('thumbnail persist failed for %s: %s', camera_uuid, e)


def load(camera_uuid: str) -> bytes | None:
    try:
        with open(_path(camera_uuid), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    return data if _is_jpeg(data) else None   # ignore any previously-persisted garbage


def remove(camera_uuid: str) -> None:
    try:
        os.unlink(_path(camera_uuid))
    except OSError:
        pass
