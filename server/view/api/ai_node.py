from flask import Blueprint, g, request

from server.controller.ai_node import AiNodeController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_ai_node', __name__, url_prefix='/api/v1/ai-nodes')


@context.route('', methods=('GET',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def list_nodes():
    return ResponseBuilder.success({'items': AiNodeController.list_nodes()})


@context.route('', methods=('POST',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def create_node():
    return ResponseBuilder.success(AiNodeController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>/token', methods=('POST',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def issue_token(node_id):
    return ResponseBuilder.success(
        AiNodeController.issue_token(node_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def update_node(node_id):
    return ResponseBuilder.success(
        AiNodeController.update(node_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>/drain', methods=('POST',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def drain_node(node_id):
    AiNodeController.drain(node_id)
    return ResponseBuilder.success()


@context.route('/<int:node_id>', methods=('DELETE',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def delete_node(node_id):
    AiNodeController.delete(node_id)
    return ResponseBuilder.success()
