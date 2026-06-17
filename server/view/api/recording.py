from flask import Blueprint, g, request

from server.controller.recording import RecordingController
from server.decorator import camera_scope_guard, login_required, permission_required
from server.model.camera import Camera
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_recording', __name__, url_prefix='/api/v1/recording')


def _camera(camera_uuid):
    return Camera.get_by_uuid(camera_uuid)


@context.route('/cameras/<camera_uuid>/status', methods=('GET',))
@login_required
@permission_required('recordings', 'read')
@map_errors
def status(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    return ResponseBuilder.success(RecordingController.get_status(_camera(camera_uuid)))


@context.route('/cameras/<camera_uuid>/mode', methods=('PUT', 'POST'))
@login_required
@permission_required('recordings', 'control')
@map_errors
def set_mode(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    mode = (request.get_json(silent=True) or {}).get('mode')
    return ResponseBuilder.success(RecordingController.set_mode(_camera(camera_uuid), mode, g.current_user))


@context.route('/cameras/<camera_uuid>/manual/start', methods=('POST',))
@login_required
@permission_required('recordings', 'control')
@map_errors
def manual_start(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(
        RecordingController.manual_start(_camera(camera_uuid), body.get('note'), g.current_user,
                                         duration_s=body.get('duration_s')))


@context.route('/cameras/<camera_uuid>/manual/stop', methods=('POST',))
@login_required
@permission_required('recordings', 'control')
@map_errors
def manual_stop(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    recording_id = (request.get_json(silent=True) or {}).get('recording_id')
    return ResponseBuilder.success(RecordingController.manual_stop(_camera(camera_uuid), recording_id, g.current_user))


@context.route('/recordings/<int:recording_id>/protect', methods=('POST',))
@login_required
@permission_required('recordings', 'control')
@map_errors
def protect(recording_id):
    protected = bool((request.get_json(silent=True) or {}).get('protected', True))
    return ResponseBuilder.success(RecordingController.protect(recording_id, protected, g.current_user))


@context.route('/health', methods=('GET',))
@login_required
@permission_required('storage', 'read')
@map_errors
def health():
    return ResponseBuilder.success({'cameras': RecordingController.health_all()})
