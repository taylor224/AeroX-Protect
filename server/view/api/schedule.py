from flask import Blueprint, g, request

from server.controller.schedule import ScheduleController
from server.decorator import camera_scope_guard, login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_schedule', __name__, url_prefix='/api/v1')


@context.route('/cameras/<camera_uuid>/schedule', methods=('GET',))
@login_required
@permission_required('schedules', 'read')
@map_errors
def get_schedule(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    return ResponseBuilder.success(ScheduleController.get_schedule(camera_uuid))


@context.route('/cameras/<camera_uuid>/schedule', methods=('PUT', 'POST'))
@login_required
@permission_required('schedules', 'update')
@map_errors
def replace_schedule(camera_uuid):
    err = camera_scope_guard(camera_uuid, 'view')
    if err:
        return err
    rules = (request.get_json(silent=True) or {}).get('rules', [])
    return ResponseBuilder.success(ScheduleController.replace_schedule(camera_uuid, rules, g.current_user))


@context.route('/schedules/apply-group', methods=('POST',))
@login_required
@permission_required('schedules', 'update')
@map_errors
def apply_group():
    data = request.get_json(silent=True) or {}
    # scope is enforced per camera inside the controller (out-of-scope cameras are skipped)
    return ResponseBuilder.success(
        ScheduleController.apply_group(data.get('rules', []), data.get('camera_ids', []), g.current_user))
