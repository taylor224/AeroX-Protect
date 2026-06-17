"""Playback: timeline, segment range serving, HLS, on-demand frame (PLAN P2 §7).

JSON endpoints (timeline/segments) use header auth via decorators. Media endpoints
(data/m3u8/frame/thumb) accept a header OR `?access_token=` because they're loaded by
<video>/hls.js. All check playback:read + camera scope; segment paths are built from
disk_id+rel_path only (no user path input → no traversal, §13)."""
import os
import subprocess
from datetime import datetime

from flask import Blueprint, Response, g, request, send_file

import config
from server.decorator import camera_scope_guard, login_required, permission_required
from server.model import UTC
from server.model.camera import Camera
from server.model.disk import Disk
from server.model.segment import Segment
from server.service import ffmpeg, playback_planner, storage_manager
from server.service.permission import PermissionService
from server.service.token import TokenService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_playback', __name__, url_prefix='/api/v1/playback')


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _media_auth():
    """(user, token) from header or ?access_token; or (None, None)."""
    token = None
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        token = header[7:].strip()
    token = token or request.args.get('access_token')
    if not token:
        return None, None
    try:
        user, _ = TokenService.verify_access(token)
        return user, token
    except Exception:
        return None, None


def _media_camera(user, camera_uuid):
    if not PermissionService.has(user, 'playback', 'read'):
        return None
    if not PermissionService.has_camera_scope(user, camera_uuid, 'view'):
        return None
    try:
        return Camera.get_by_uuid(camera_uuid)
    except Exception:
        return None


def _segment_abs(seg: Segment) -> str | None:
    disk = Disk.get_by_id(seg.disk_id)
    if not disk:
        return None
    path = storage_manager.abs_path(disk, seg.rel_path)
    return path if os.path.exists(path) else None


# ── JSON (axios/header auth) ──────────────────────────────────────────────────
@context.route('/cameras/<camera_uuid>/timeline', methods=('GET',))
@login_required
@permission_required('playback', 'read')
@map_errors
def timeline(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    camera = Camera.get_by_uuid(camera_uuid)
    start = _parse_ms(request.args.get('from'))
    end = _parse_ms(request.args.get('to'))
    if not start or not end:
        return ResponseBuilder.bad_request('from/to (epoch ms) required')
    return ResponseBuilder.success(playback_planner.build_timeline(camera.id, start, end))


@context.route('/cameras/<camera_uuid>/segments', methods=('GET',))
@login_required
@permission_required('playback', 'read')
@map_errors
def segments(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    camera = Camera.get_by_uuid(camera_uuid)
    start = _parse_ms(request.args.get('from'))
    end = _parse_ms(request.args.get('to'))
    if not start or not end:
        return ResponseBuilder.bad_request('from/to (epoch ms) required')
    return ResponseBuilder.success({'segments': playback_planner.get_segments(camera.id, start, end)})


# ── media (header or query token) ─────────────────────────────────────────────
@context.route('/cameras/<camera_uuid>/index.m3u8', methods=('GET',))
def hls(camera_uuid):
    user, token = _media_auth()
    if not user:
        return ResponseBuilder.no_permission('authentication_required')
    camera = _media_camera(user, camera_uuid)
    if not camera:
        return ResponseBuilder.forbidden('playback_denied')
    start, end = _parse_ms(request.args.get('from')), _parse_ms(request.args.get('to'))
    if not start or not end:
        return ResponseBuilder.bad_request('from/to required')
    playlist = playback_planner.build_m3u8(camera.id, start, end, token)
    return Response(playlist, mimetype='application/vnd.apple.mpegurl')


@context.route('/segments/<int:segment_id>/data', methods=('GET',))
def segment_data(segment_id):
    user, _ = _media_auth()
    if not user:
        return ResponseBuilder.no_permission('authentication_required')
    seg = Segment.get_by_id(segment_id)
    if not seg:
        return ResponseBuilder.not_found('segment_not_found')
    camera = Camera.get_by_id(seg.camera_id)
    if not _media_camera(user, camera.uuid):
        return ResponseBuilder.forbidden('playback_denied')
    path = _segment_abs(seg)
    if not path:
        return ResponseBuilder.not_found('segment_unavailable')   # disk offline → gap
    mimetype = 'video/mp2t' if seg.container == 'mpegts' else 'video/mp4'
    return send_file(path, mimetype=mimetype, conditional=True, max_age=3600)


@context.route('/cameras/<camera_uuid>/frame', methods=('GET',))
def frame(camera_uuid):
    user, _ = _media_auth()
    if not user:
        return ResponseBuilder.no_permission('authentication_required')
    camera = _media_camera(user, camera_uuid)
    if not camera:
        return ResponseBuilder.forbidden('playback_denied')
    ts = _parse_ms(request.args.get('ts'))
    if not ts:
        return ResponseBuilder.bad_request('ts required')
    seg = Segment.get_at(camera.id, ts)
    if not seg:
        return ResponseBuilder.not_found('no_segment_at_ts')
    path = _segment_abs(seg)
    if not path:
        return ResponseBuilder.not_found('segment_unavailable')
    offset = max(0.0, (ts - seg.start_ts).total_seconds())
    jpeg = _extract_frame(path, offset)
    if not jpeg:
        return ResponseBuilder.not_found('frame_unavailable')
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'max-age=60'})


@context.route('/segments/<int:segment_id>/thumb', methods=('GET',))
def thumb(segment_id):
    user, _ = _media_auth()
    if not user:
        return ResponseBuilder.no_permission('authentication_required')
    seg = Segment.get_by_id(segment_id)
    if not seg:
        return ResponseBuilder.not_found('segment_not_found')
    camera = Camera.get_by_id(seg.camera_id)
    if not _media_camera(user, camera.uuid):
        return ResponseBuilder.forbidden('playback_denied')
    cache_key = '%ssegthumb:%s' % (config.THUMB_CACHE_PREFIX, segment_id)
    try:
        from server.service.token import get_redis
        cached = get_redis().get(cache_key)
        if cached:
            data = cached.encode('latin-1') if isinstance(cached, str) else cached
            return Response(data, mimetype='image/jpeg')
    except Exception:
        pass
    path = _segment_abs(seg)
    if not path:
        return ResponseBuilder.not_found('segment_unavailable')
    jpeg = _extract_frame(path, 0.0)
    if not jpeg:
        return ResponseBuilder.not_found('thumb_unavailable')
    try:
        from server.service.token import get_redis
        get_redis().setex(cache_key, 3600, jpeg)
    except Exception:
        pass
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'max-age=300'})


def _extract_frame(segment_path: str, offset: float) -> bytes | None:
    try:
        out = subprocess.run(ffmpeg.build_frame_cmd(segment_path, offset),
                             capture_output=True, timeout=15)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except (subprocess.SubprocessError, OSError):
        return None
