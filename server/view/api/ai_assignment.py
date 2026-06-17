from flask import Blueprint, g, request

from server.controller.ai_assignment import AiAssignmentController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_ai_assignment', __name__, url_prefix='/api/v1/ai/assignments')


@context.route('', methods=('GET',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def list_assignments():
    return ResponseBuilder.success(AiAssignmentController.list_assignments())


@context.route('/rebalance', methods=('POST',))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def rebalance():
    return ResponseBuilder.success(AiAssignmentController.rebalance())


@context.route('/<int:camera_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('ai_nodes', 'manage')
@map_errors
def pin(camera_id):
    data = request.get_json(silent=True) or {}
    if not data.get('node_id'):
        return ResponseBuilder.bad_request('node_id required')
    return ResponseBuilder.success(AiAssignmentController.pin(camera_id, int(data['node_id'])))
