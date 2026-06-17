from flask import Blueprint, g, request

from server.controller.detection_zone import DetectionZoneController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_detection_zone', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/detection-zones', methods=('GET',))
@login_required
@permission_required('zones', 'read')
@map_errors
def list_zones(camera_uuid):
    return ResponseBuilder.success({'items': DetectionZoneController.list_for_camera(g.current_user, camera_uuid)})


@context.route('/cameras/<camera_uuid>/detection-zones', methods=('POST',))
@login_required
@permission_required('zones', 'update')
@map_errors
def create_zone(camera_uuid):
    return ResponseBuilder.success(
        DetectionZoneController.create(g.current_user, camera_uuid, request.get_json(silent=True) or {}))


@context.route('/detection-zones/<int:zone_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('zones', 'update')
@map_errors
def update_zone(zone_id):
    return ResponseBuilder.success(
        DetectionZoneController.update(g.current_user, zone_id, request.get_json(silent=True) or {}))


@context.route('/detection-zones/<int:zone_id>', methods=('DELETE',))
@login_required
@permission_required('zones', 'update')
@map_errors
def delete_zone(zone_id):
    DetectionZoneController.delete(g.current_user, zone_id)
    return ResponseBuilder.success()
