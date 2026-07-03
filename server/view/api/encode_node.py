from flask import Blueprint, g, request

from server.controller.encode_node import EncodeNodeController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_encode_node', __name__, url_prefix='/api/v1/encoding-nodes')


@context.route('', methods=('GET',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def list_nodes():
    return ResponseBuilder.success({'items': EncodeNodeController.list_nodes()})


@context.route('', methods=('POST',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def create_node():
    return ResponseBuilder.success(EncodeNodeController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>/token', methods=('POST',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def issue_token(node_id):
    return ResponseBuilder.success(
        EncodeNodeController.issue_token(node_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def update_node(node_id):
    return ResponseBuilder.success(
        EncodeNodeController.update(node_id, request.get_json(silent=True) or {}, g.current_user))


@context.route('/<int:node_id>/drain', methods=('POST',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def drain_node(node_id):
    EncodeNodeController.drain(node_id)
    return ResponseBuilder.success()


@context.route('/<int:node_id>', methods=('DELETE',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def delete_node(node_id):
    EncodeNodeController.delete(node_id)
    return ResponseBuilder.success()


@context.route('/assignments', methods=('GET',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def list_assignments():
    return ResponseBuilder.success(EncodeNodeController.list_assignments())


@context.route('/assignments/rebalance', methods=('POST',))
@login_required
@permission_required('encoding_nodes', 'manage')
@map_errors
def rebalance():
    return ResponseBuilder.success(EncodeNodeController.rebalance())
