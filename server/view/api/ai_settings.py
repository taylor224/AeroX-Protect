from flask import Blueprint, g, request

from server.controller.ai_settings import AiSettingsController
from server.decorator import camera_scope_guard, login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_ai_settings', __name__, url_prefix='/api/v1')


@context.route('/ai/settings', methods=('GET',))
@login_required
@permission_required('ai', 'read')
@map_errors
def get_settings():
    camera_uuid = request.args.get('camera_id')
    if camera_uuid:
        err = camera_scope_guard(camera_uuid, 'view')
        if err:
            return err
    return ResponseBuilder.success(AiSettingsController.get(camera_uuid))


@context.route('/ai/settings', methods=('PUT', 'POST'))
@login_required
@permission_required('ai', 'update')
@map_errors
def update_settings():
    return ResponseBuilder.success(
        AiSettingsController.update_global(request.get_json(silent=True) or {}, g.current_user))


@context.route('/cameras/<camera_uuid>/ai-settings', methods=('PUT', 'POST'))
@login_required
@permission_required('ai', 'update')
@map_errors
def update_camera_settings(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    return ResponseBuilder.success(
        AiSettingsController.update_camera(camera_uuid, request.get_json(silent=True) or {}, g.current_user))
