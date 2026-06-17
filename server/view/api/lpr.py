from flask import Blueprint, g, request

from server.controller.lpr import LprController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_lpr', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/plates', methods=('GET',))
@login_required
@permission_required('lpr', 'read')
@map_errors
def list_for_camera(camera_uuid):
    return ResponseBuilder.success({'items': LprController.list_for_camera(g.current_user, camera_uuid, request.args)})


@context.route('/plates/search', methods=('GET',))
@login_required
@permission_required('lpr', 'read')
@map_errors
def search():
    return ResponseBuilder.success(LprController.search(g.current_user, request.args))


@context.route('/plate-lists', methods=('GET',))
@login_required
@permission_required('lpr', 'read')
@map_errors
def list_entries():
    return ResponseBuilder.success({'items': LprController.list_entries(g.current_user, request.args)})


@context.route('/plate-lists', methods=('POST',))
@login_required
@permission_required('lpr', 'manage')
@map_errors
def create_entry():
    return ResponseBuilder.success(LprController.create_entry(g.current_user, request.get_json(silent=True) or {}))


@context.route('/plate-lists/<int:entry_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('lpr', 'manage')
@map_errors
def update_entry(entry_id):
    return ResponseBuilder.success(
        LprController.update_entry(g.current_user, entry_id, request.get_json(silent=True) or {}))


@context.route('/plate-lists/<int:entry_id>', methods=('DELETE',))
@login_required
@permission_required('lpr', 'manage')
@map_errors
def delete_entry(entry_id):
    LprController.delete_entry(g.current_user, entry_id)
    return ResponseBuilder.success()
