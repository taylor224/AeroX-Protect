from flask import Blueprint, g, request

from server.controller.edge_recording import EdgeRecordingController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_edge_recording', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/edge/gaps', methods=('GET',))
@login_required
@permission_required('recordings', 'read')
@map_errors
def preview_gaps(camera_uuid):
    return ResponseBuilder.success(EdgeRecordingController.preview_gaps(g.current_user, camera_uuid, request.args))


@context.route('/cameras/<camera_uuid>/edge/jobs', methods=('GET',))
@login_required
@permission_required('recordings', 'read')
@map_errors
def list_jobs(camera_uuid):
    return ResponseBuilder.success({'items': EdgeRecordingController.list_jobs(g.current_user, camera_uuid)})


@context.route('/cameras/<camera_uuid>/edge/import', methods=('POST',))
@login_required
@permission_required('recordings', 'control')
@map_errors
def create_import(camera_uuid):
    return ResponseBuilder.success(
        EdgeRecordingController.create_import(g.current_user, camera_uuid, request.get_json(silent=True) or {}))
