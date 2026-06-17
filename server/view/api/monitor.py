from flask import Blueprint, g, request

from server.controller.monitor import MonitorController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_monitor', __name__, url_prefix='/api/v1/monitors')


@context.route('', methods=('GET',))
@login_required
@permission_required('monitors', 'read')
@map_errors
def list_monitors():
    return ResponseBuilder.success({'items': MonitorController.list_monitors()})


@context.route('', methods=('POST',))
@login_required
@permission_required('monitors', 'manage')
@map_errors
def create_monitor():
    return ResponseBuilder.success(MonitorController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('monitors', 'manage')
@map_errors
def update_monitor(uuid):
    return ResponseBuilder.success(MonitorController.update(uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<uuid>', methods=('DELETE',))
@login_required
@permission_required('monitors', 'manage')
@map_errors
def delete_monitor(uuid):
    MonitorController.delete(uuid)
    return ResponseBuilder.success()


@context.route('/<uuid>/pair-code', methods=('POST',))
@login_required
@permission_required('monitors', 'manage')
@map_errors
def pair_code(uuid):
    return ResponseBuilder.success(MonitorController.pair_code(uuid, request.remote_addr, g.current_user))


@context.route('/<uuid>/revoke', methods=('POST',))
@login_required
@permission_required('monitors', 'manage')
@map_errors
def revoke_monitor(uuid):
    return ResponseBuilder.success(MonitorController.revoke(uuid))
