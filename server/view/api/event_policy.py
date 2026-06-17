from flask import Blueprint, g, request

from server.controller.event_policy import EventPolicyController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_event_policy', __name__, url_prefix='/api/v1/event-policies')


@context.route('', methods=('GET',))
@login_required
@permission_required('policies', 'read')
@map_errors
def list_policies():
    return ResponseBuilder.success({'items': EventPolicyController.list_policies(request.args.get('camera_id'))})


@context.route('', methods=('POST',))
@login_required
@permission_required('policies', 'update')
@map_errors
def create_policy():
    return ResponseBuilder.success(EventPolicyController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/resolve', methods=('POST',))
@login_required
@permission_required('policies', 'read')
@map_errors
def resolve_policy():
    return ResponseBuilder.success(EventPolicyController.resolve_preview(request.get_json(silent=True) or {}))


@context.route('/<int:policy_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('policies', 'update')
@map_errors
def update_policy(policy_id):
    return ResponseBuilder.success(
        EventPolicyController.update(policy_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:policy_id>', methods=('DELETE',))
@login_required
@permission_required('policies', 'update')
@map_errors
def delete_policy(policy_id):
    EventPolicyController.delete(policy_id)
    return ResponseBuilder.success()
