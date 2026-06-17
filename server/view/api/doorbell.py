from flask import Blueprint, g, request

from server.controller.doorbell import DoorbellController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_doorbell', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/doorbell', methods=('POST',))
@login_required
@permission_required('events', 'update')
@map_errors
def ring(camera_uuid):
    return ResponseBuilder.success(
        DoorbellController.ring(g.current_user, camera_uuid, request.get_json(silent=True) or {}))
