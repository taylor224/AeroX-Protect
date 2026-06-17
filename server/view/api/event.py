import os
import subprocess
from datetime import datetime

from flask import Blueprint, Response, g, request

from server.controller.event import EventController, _parse_ms
from server.decorator import login_required, permission_required
from server.model.disk import Disk
from server.model.event import Event
from server.model.segment import Segment
from server.service import ffmpeg, storage_manager
from server.service.permission import PermissionService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_event', __name__, url_prefix='/api/v1/events')


@context.route('', methods=('GET',))
@login_required
@permission_required('events', 'read')
@map_errors
def list_events():
    return ResponseBuilder.success(EventController.list_events(g.current_user, request.args))


@context.route('/timeline', methods=('GET',))
@login_required
@permission_required('events', 'read')
@map_errors
def timeline():
    from server.model.camera import Camera  # noqa
    camera_uuid = request.args.get('camera_id')   # accepts uuid here
    start, end = _parse_ms(request.args.get('start')), _parse_ms(request.args.get('end'))
    if not camera_uuid or not start or not end:
        return ResponseBuilder.bad_request('camera_id/start/end required')
    types = request.args.getlist('type') or None
    return ResponseBuilder.success(EventController.timeline(g.current_user, camera_uuid, start, end, types))


@context.route('/simulate', methods=('POST',))
@login_required
@permission_required('events', 'update')
@map_errors
def simulate():
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(EventController.simulate(g.current_user, data.get('camera_uuid', ''), data))


@context.route('/<int:event_id>', methods=('GET',))
@login_required
@permission_required('events', 'read')
@map_errors
def get_event(event_id):
    return ResponseBuilder.success(EventController.get_event(g.current_user, event_id))


@context.route('/<int:event_id>/overlay', methods=('GET',))
@login_required
@permission_required('events', 'read')
@map_errors
def overlay(event_id):
    return ResponseBuilder.success(EventController.overlay(g.current_user, event_id))


@context.route('/<int:event_id>/snapshot', methods=('GET',))
@login_required
@permission_required('events', 'read')
@map_errors
def snapshot(event_id):
    ev = EventController._scoped_event(g.current_user, event_id)
    jpeg = _event_frame(ev)
    if not jpeg:
        return ResponseBuilder.not_found('snapshot_unavailable')
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=300'})


@context.route('/<int:event_id>/save', methods=('POST',))
@login_required
@permission_required('events', 'update')
@map_errors
def save_event(event_id):
    return ResponseBuilder.success(EventController.save_event(g.current_user, event_id, request.get_json(silent=True) or {}))


@context.route('/<int:event_id>', methods=('DELETE',))
@login_required
@permission_required('events', 'delete')
@map_errors
def delete_event(event_id):
    EventController.delete_event(g.current_user, event_id)
    return ResponseBuilder.success()


def _event_frame(ev: Event) -> bytes | None:
    """Stored snapshot or on-demand frame from the segment at the event time."""
    seg = Segment.get_at(ev.camera_id, ev.start_ts)
    if not seg:
        return None
    disk = Disk.get_by_id(seg.disk_id)
    if not disk:
        return None
    path = storage_manager.abs_path(disk, seg.rel_path)
    if not os.path.exists(path):
        return None
    offset = max(0.0, (ev.start_ts - seg.start_ts).total_seconds())
    try:
        out = subprocess.run(ffmpeg.build_frame_cmd(path, offset), capture_output=True, timeout=15)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except (subprocess.SubprocessError, OSError):
        return None
