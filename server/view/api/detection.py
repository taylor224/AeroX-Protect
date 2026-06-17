from flask import Blueprint, Response, g, request

from server.controller.detection import DetectionController, _parse_ms
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_detection', __name__, url_prefix='/api/v1/detections')


@context.route('/search', methods=('GET',))
@login_required
@permission_required('detections', 'read')
@map_errors
def search():
    return ResponseBuilder.success(DetectionController.search(g.current_user, request.args))


@context.route('/timeline', methods=('GET',))
@login_required
@permission_required('detections', 'read')
@map_errors
def timeline():
    camera_uuid = request.args.get('camera_id')      # uuid here
    start, end = _parse_ms(request.args.get('start')), _parse_ms(request.args.get('end'))
    if not camera_uuid or not start or not end:
        return ResponseBuilder.bad_request('camera_id/start/end required')
    labels = request.args.getlist('label') or None
    return ResponseBuilder.success(DetectionController.timeline(g.current_user, camera_uuid, start, end, labels))


@context.route('/overlay', methods=('GET',))
@login_required
@permission_required('detections', 'read')
@map_errors
def overlay():
    camera_uuid = request.args.get('camera_id')
    start, end = _parse_ms(request.args.get('start')), _parse_ms(request.args.get('end'))
    if not camera_uuid or not start or not end:
        return ResponseBuilder.bad_request('camera_id/start/end required')
    labels = request.args.getlist('label') or None
    return ResponseBuilder.success(DetectionController.overlay(g.current_user, camera_uuid, start, end, labels))


@context.route('/<int:detection_id>', methods=('GET',))
@login_required
@permission_required('detections', 'read')
@map_errors
def get_detection(detection_id):
    return ResponseBuilder.success(DetectionController.get(g.current_user, detection_id))


@context.route('/<int:detection_id>/snapshot', methods=('GET',))
@login_required
@permission_required('detections', 'read')
@map_errors
def snapshot(detection_id):
    jpeg = DetectionController.snapshot(g.current_user, detection_id)
    if not jpeg:
        return ResponseBuilder.not_found('snapshot_unavailable')
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=300'})
