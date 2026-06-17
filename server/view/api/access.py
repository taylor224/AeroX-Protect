from flask import Blueprint, g, request

from server.controller.access import AccessController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_access', __name__, url_prefix='/api/v1')


# ── doors ─────────────────────────────────────────────────────────────────────
@context.route('/access/doors', methods=('GET',))
@login_required
@permission_required('access', 'read')
@map_errors
def list_doors():
    return ResponseBuilder.success({'items': AccessController.list_doors()})


@context.route('/access/doors', methods=('POST',))
@login_required
@permission_required('access', 'manage')
@map_errors
def create_door():
    return ResponseBuilder.success(AccessController.create_door(request.get_json(silent=True) or {}, g.current_user))


@context.route('/access/doors/<int:door_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('access', 'manage')
@map_errors
def update_door(door_id):
    return ResponseBuilder.success(
        AccessController.update_door(door_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/access/doors/<int:door_id>', methods=('DELETE',))
@login_required
@permission_required('access', 'manage')
@map_errors
def delete_door(door_id):
    AccessController.delete_door(door_id, g.current_user)
    return ResponseBuilder.success()


# ── control ─────────────────────────────────────────────────────────────────--
@context.route('/access/doors/<int:door_id>/unlock', methods=('POST',))
@login_required
@permission_required('access', 'control')
@map_errors
def unlock_door(door_id):
    return ResponseBuilder.success(AccessController.unlock(door_id, g.current_user))


@context.route('/access/doors/<int:door_id>/swipe', methods=('POST',))
@login_required
@permission_required('access', 'control')
@map_errors
def swipe(door_id):
    return ResponseBuilder.success(AccessController.swipe(door_id, request.get_json(silent=True) or {}))


# ── credentials ─────────────────────────────────────────────────────────────--
@context.route('/access/credentials', methods=('GET',))
@login_required
@permission_required('access', 'read')
@map_errors
def list_credentials():
    return ResponseBuilder.success({'items': AccessController.list_credentials(request.args)})


@context.route('/access/credentials', methods=('POST',))
@login_required
@permission_required('access', 'manage')
@map_errors
def create_credential():
    return ResponseBuilder.success(
        AccessController.create_credential(request.get_json(silent=True) or {}, g.current_user))


@context.route('/access/credentials/<int:cred_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('access', 'manage')
@map_errors
def update_credential(cred_id):
    return ResponseBuilder.success(
        AccessController.update_credential(cred_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/access/credentials/<int:cred_id>', methods=('DELETE',))
@login_required
@permission_required('access', 'manage')
@map_errors
def delete_credential(cred_id):
    AccessController.delete_credential(cred_id, g.current_user)
    return ResponseBuilder.success()


# ── events ──────────────────────────────────────────────────────────────────--
@context.route('/access/events', methods=('GET',))
@login_required
@permission_required('access', 'read')
@map_errors
def list_events():
    return ResponseBuilder.success({'items': AccessController.list_events(request.args)})
