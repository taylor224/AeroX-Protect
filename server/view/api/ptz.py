from flask import Blueprint, request

from server.controller.ptz import PtzController
from server.decorator import login_required, permission_required, ptz_guard
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_ptz', __name__, url_prefix='/api/v1/cameras')


@context.route('/<camera_uuid>/ptz', methods=('POST',))
@login_required
@permission_required('ptz', 'control')
@map_errors
def ptz(camera_uuid):
    err = ptz_guard(camera_uuid)
    if err:
        return err
    return ResponseBuilder.success(PtzController.execute(camera_uuid, request.get_json(silent=True) or {}))


@context.route('/<camera_uuid>/ptz/presets', methods=('GET',))
@login_required
@permission_required('live', 'read')
@map_errors
def list_presets(camera_uuid):
    err = ptz_guard(camera_uuid)
    if err:
        return err
    return ResponseBuilder.success({'presets': PtzController.list_presets(camera_uuid)})


@context.route('/<camera_uuid>/ptz/presets', methods=('POST',))
@login_required
@permission_required('ptz', 'control')
@map_errors
def save_preset(camera_uuid):
    err = ptz_guard(camera_uuid)
    if err:
        return err
    return ResponseBuilder.success(PtzController.save_preset(camera_uuid, request.get_json(silent=True) or {}))


@context.route('/<camera_uuid>/ptz/presets/<token>/goto', methods=('POST',))
@login_required
@permission_required('ptz', 'control')
@map_errors
def goto_preset(camera_uuid, token):
    err = ptz_guard(camera_uuid)
    if err:
        return err
    return ResponseBuilder.success(PtzController.execute(camera_uuid, {'action': 'goto_preset', 'token': token}))


@context.route('/<camera_uuid>/ptz/presets/<token>', methods=('DELETE',))
@login_required
@permission_required('ptz', 'control')
@map_errors
def remove_preset(camera_uuid, token):
    err = ptz_guard(camera_uuid)
    if err:
        return err
    PtzController.remove_preset(camera_uuid, token)
    return ResponseBuilder.success()
