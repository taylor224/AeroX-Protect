from flask import Blueprint, g, request

from server.controller.camera import CameraController
from server.decorator import login_required, permission_required
from server.util.pagination import build_page, parse_pagination
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_camera', __name__, url_prefix='/api/v1/cameras')


@context.route('', methods=('GET',))
@login_required
@permission_required('cameras', 'read')
@map_errors
def list_cameras():
    p = parse_pagination(request.args)
    total, items = CameraController.get_list(p['page'], p['items_per_page'], p['q'], p['sort'], p['order'])
    return ResponseBuilder.success(build_page(items, total, p['page'], p['items_per_page']))


@context.route('', methods=('POST',))
@login_required
@permission_required('cameras', 'create')
@map_errors
def create_camera():
    return ResponseBuilder.success(CameraController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/batch', methods=('POST',))
@login_required
@permission_required('cameras', 'create')
@map_errors
def batch_create_cameras():
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(
        CameraController.batch_create(body.get('items') or [], body.get('common') or {}, g.current_user))


@context.route('/<camera_uuid>', methods=('GET',))
@login_required
@permission_required('cameras', 'read')
@map_errors
def get_camera(camera_uuid):
    return ResponseBuilder.success(CameraController.get(camera_uuid))


@context.route('/<camera_uuid>', methods=('POST',))
@login_required
@permission_required('cameras', 'update')
@map_errors
def update_camera(camera_uuid):
    return ResponseBuilder.success(
        CameraController.update(camera_uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<camera_uuid>', methods=('DELETE',))
@login_required
@permission_required('cameras', 'delete')
@map_errors
def delete_camera(camera_uuid):
    CameraController.delete(camera_uuid, g.current_user)
    return ResponseBuilder.success()


@context.route('/<camera_uuid>/reprobe', methods=('POST',))
@login_required
@permission_required('cameras', 'update')
@map_errors
def reprobe_camera(camera_uuid):
    return ResponseBuilder.success(CameraController.reprobe(camera_uuid, g.current_user))


@context.route('/<camera_uuid>/health', methods=('GET',))
@login_required
@permission_required('cameras', 'read')
@map_errors
def camera_health(camera_uuid):
    return ResponseBuilder.success(CameraController.health(camera_uuid))


@context.route('/<camera_uuid>/streams', methods=('GET',))
@login_required
@permission_required('cameras', 'read')
@map_errors
def camera_streams(camera_uuid):
    return ResponseBuilder.success({'streams': CameraController.streams(camera_uuid)})
