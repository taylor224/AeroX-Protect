"""/api/v1/system — native-install self-update + service status (P-Windows).

Every route answers 501 platform_unsupported when the deployment has no launcher
(Docker) so the frontend card can self-hide. Update apply is settings:update +
audit-logged; the returned HMAC ticket lets the browser keep polling the launcher
through /updater/* while the backend itself restarts.
"""
from flask import Blueprint, g, request

from server.controller.system import LauncherUnreachable, SystemController, UpdateAlreadyRunning
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_system', __name__, url_prefix='/api/v1/system')


def _unsupported():
    r = ResponseBuilder.internal_server_error('platform_unsupported')
    r.status_code = 501
    return r


@context.route('/update/check', methods=('GET',))
@login_required
@permission_required('settings', 'read')
@map_errors
def check_update():
    if not SystemController.available():
        return _unsupported()
    try:
        force = request.args.get('force') in ('1', 'true')
        return ResponseBuilder.success(SystemController.check_update(force=force))
    except LauncherUnreachable:
        return ResponseBuilder.internal_server_error('launcher_unreachable')


@context.route('/update/apply', methods=('POST',))
@login_required
@permission_required('settings', 'update')
@map_errors
def apply_update():
    if not SystemController.available():
        return _unsupported()
    body = request.get_json(silent=True) or {}
    try:
        return ResponseBuilder.success(
            SystemController.apply_update(g.current_user, body.get('version')))
    except UpdateAlreadyRunning:
        return ResponseBuilder.conflict('update_already_running')
    except LauncherUnreachable:
        return ResponseBuilder.internal_server_error('launcher_unreachable')


@context.route('/update/status', methods=('GET',))
@login_required
@permission_required('settings', 'read')
@map_errors
def update_status():
    if not SystemController.available():
        return _unsupported()
    try:
        return ResponseBuilder.success(SystemController.update_status())
    except LauncherUnreachable:
        return ResponseBuilder.internal_server_error('launcher_unreachable')


@context.route('/services', methods=('GET',))
@login_required
@permission_required('settings', 'read')
@map_errors
def services():
    if not SystemController.available():
        return _unsupported()
    try:
        return ResponseBuilder.success(SystemController.services())
    except LauncherUnreachable:
        return ResponseBuilder.internal_server_error('launcher_unreachable')
