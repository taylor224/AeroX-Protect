from flask import Blueprint, g, request

from server.controller.federation import FederationController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_federation', __name__, url_prefix='/api/v1')


@context.route('/federation/members', methods=('GET',))
@login_required
@permission_required('federation', 'read')
@map_errors
def list_members():
    return ResponseBuilder.success({'items': FederationController.list_members()})


@context.route('/federation/members', methods=('POST',))
@login_required
@permission_required('federation', 'manage')
@map_errors
def create_member():
    return ResponseBuilder.success(FederationController.create_member(request.get_json(silent=True) or {}, g.current_user))


@context.route('/federation/members/<int:member_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('federation', 'manage')
@map_errors
def update_member(member_id):
    return ResponseBuilder.success(
        FederationController.update_member(member_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/federation/members/<int:member_id>', methods=('DELETE',))
@login_required
@permission_required('federation', 'manage')
@map_errors
def delete_member(member_id):
    FederationController.delete_member(member_id, g.current_user)
    return ResponseBuilder.success()


@context.route('/federation/members/<int:member_id>/sync', methods=('POST',))
@login_required
@permission_required('federation', 'manage')
@map_errors
def sync_member(member_id):
    return ResponseBuilder.success(FederationController.sync_member(member_id))


@context.route('/federation/cameras', methods=('GET',))
@login_required
@permission_required('federation', 'read')
@map_errors
def aggregate_cameras():
    return ResponseBuilder.success(FederationController.aggregate_cameras())


@context.route('/federation/events', methods=('GET',))
@login_required
@permission_required('federation', 'read')
@map_errors
def aggregate_events():
    return ResponseBuilder.success(FederationController.aggregate_events(request.args))
