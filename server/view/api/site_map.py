from flask import Blueprint, g, request

from server.controller.site_map import MapController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_map', __name__, url_prefix='/api/v1/maps')


@context.route('', methods=('GET',))
@login_required
@permission_required('maps', 'read')
@map_errors
def list_maps():
    return ResponseBuilder.success({'items': MapController.list_maps()})


@context.route('/config', methods=('GET',))
@login_required
@permission_required('maps', 'read')
@map_errors
def get_config():
    return ResponseBuilder.success(MapController.get_config())


@context.route('/config', methods=('PUT', 'POST'))
@login_required
@permission_required('maps', 'update')
@map_errors
def update_config():
    return ResponseBuilder.success(MapController.update_config(request.get_json(silent=True) or {}, g.current_user))


@context.route('', methods=('POST',))
@login_required
@permission_required('maps', 'update')
@map_errors
def create_map():
    return ResponseBuilder.success(MapController.create_map(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:map_id>', methods=('GET',))
@login_required
@permission_required('maps', 'read')
@map_errors
def get_map(map_id):
    return ResponseBuilder.success(MapController.get_map(map_id))


@context.route('/<int:map_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('maps', 'update')
@map_errors
def update_map(map_id):
    return ResponseBuilder.success(MapController.update_map(map_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:map_id>', methods=('DELETE',))
@login_required
@permission_required('maps', 'update')
@map_errors
def delete_map(map_id):
    MapController.delete_map(map_id)
    return ResponseBuilder.success()


@context.route('/<int:map_id>/markers', methods=('PUT',))
@login_required
@permission_required('maps', 'update')
@map_errors
def replace_markers(map_id):
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(MapController.replace_markers(map_id, body.get('markers') or []))
