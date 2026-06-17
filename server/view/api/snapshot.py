from flask import Blueprint, Response

from server.controller.ptz import _driver_for
from server.decorator import camera_scope_guard, login_required, permission_required
from server.driver.base import DriverError
from server.driver.go2rtc import Go2rtcDriver
from server.model.camera import Camera
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_snapshot', __name__, url_prefix='/api/v1/cameras')


def _get_jpeg(camera_uuid: str) -> bytes | None:
    camera = Camera.get_by_uuid(camera_uuid)
    streams = camera.streams
    # prefer the full (main) stream: it's kept warm by the recorder, so go2rtc returns a clean
    # keyframe-aligned snapshot instantly instead of a cold/pre-keyframe frame from the on-demand
    # (and, for H.265 cams, transcoded) live stream
    target = (next((s for s in streams if s.is_default_full), None)
              or next((s for s in streams if s.is_default_live), None)
              or (streams[0] if streams else None))
    if target:
        frame = Go2rtcDriver().get_frame(target.go2rtc_name)
        if frame:
            return frame
    try:  # fallback: vendor/onvif snapshot
        return _driver_for(camera).get_snapshot()
    except DriverError:
        return None


@context.route('/<camera_uuid>/snapshot', methods=('GET',))
@login_required
@permission_required('live', 'read')
@map_errors
def snapshot(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    jpeg = _get_jpeg(camera_uuid)
    if not jpeg:
        return ResponseBuilder.not_found('snapshot_unavailable')
    return Response(jpeg, content_type='image/jpeg')


@context.route('/<camera_uuid>/thumbnail', methods=('GET',))
@login_required
@permission_required('live', 'read')
@map_errors
def thumbnail(camera_uuid):
    """Cheap camera-list tile: serve the Redis-cached JPEG that camera_health_check refreshes
    every 30s (no per-request camera hit); fall back to a live frame if the cache is cold."""
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    # fresh Redis cache → durable last-frame file → live grab. The persisted file means an
    # offline camera keeps showing its last frame (no slow per-request camera hit, no blank tile).
    from server.service import thumbnail_store
    jpeg = _cached_thumb(camera_uuid) or thumbnail_store.load(camera_uuid) or _get_jpeg(camera_uuid)
    if not jpeg:
        return ResponseBuilder.not_found('thumbnail_unavailable')
    return Response(jpeg, content_type='image/jpeg', headers={'Cache-Control': 'max-age=30'})


def _cached_thumb(camera_uuid: str) -> bytes | None:
    from server.service.token import get_redis_binary
    from server.task.list.camera_health import THUMB_KEY
    try:
        return get_redis_binary().get(THUMB_KEY % camera_uuid)
    except Exception:
        return None
