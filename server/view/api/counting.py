from flask import Blueprint, g, request

from server.controller.counting import CountingController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_counting', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/counting', methods=('GET',))
@login_required
@permission_required('ai', 'count')
@map_errors
def list_lines(camera_uuid):
    return ResponseBuilder.success({'items': CountingController.list_for_camera(g.current_user, camera_uuid)})


@context.route('/cameras/<camera_uuid>/counting', methods=('POST',))
@login_required
@permission_required('ai', 'count')
@map_errors
def create_line(camera_uuid):
    return ResponseBuilder.success(
        CountingController.create(g.current_user, camera_uuid, request.get_json(silent=True) or {}))


@context.route('/counting/<int:line_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('ai', 'count')
@map_errors
def update_line(line_id):
    return ResponseBuilder.success(
        CountingController.update(g.current_user, line_id, request.get_json(silent=True) or {}))


@context.route('/counting/<int:line_id>', methods=('DELETE',))
@login_required
@permission_required('ai', 'count')
@map_errors
def delete_line(line_id):
    CountingController.delete(g.current_user, line_id)
    return ResponseBuilder.success()


@context.route('/analytics/counting', methods=('GET',))
@login_required
@permission_required('ai', 'count')
@map_errors
def analytics():
    return ResponseBuilder.success(CountingController.analytics(g.current_user, request.args))
