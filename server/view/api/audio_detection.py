from flask import Blueprint, g, request

from server.controller.audio_detection import AudioDetectionController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_audio_detection', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/audio-detections', methods=('GET',))
@login_required
@permission_required('ai', 'audio')
@map_errors
def list_for_camera(camera_uuid):
    return ResponseBuilder.success(
        {'items': AudioDetectionController.list_for_camera(g.current_user, camera_uuid, request.args)})


@context.route('/audio/labels', methods=('GET',))
@login_required
@permission_required('ai', 'audio')
@map_errors
def labels():
    return ResponseBuilder.success(AudioDetectionController.labels())
