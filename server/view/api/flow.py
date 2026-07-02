from flask import Blueprint, g, request

from server.controller.flow import FlowController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_flow', __name__, url_prefix='/api/v1')


@context.route('/automation/flows/incoming/<token>', methods=('GET', 'POST'))
@map_errors
def incoming_webhook(token):
    """Unauthenticated inbound trigger — the URL's opaque token IS the credential. Starts
    the flow bound to it from its incoming-webhook trigger nodes."""
    body = request.get_json(silent=True) if request.method == 'POST' else None
    return ResponseBuilder.success(
        FlowController.fire_incoming(token, body, dict(request.args)))


@context.route('/flows', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def list_flows():
    return ResponseBuilder.success(FlowController.list_flows(request.args))


@context.route('/flows', methods=('POST',))
@login_required
@permission_required('rules', 'create')
@map_errors
def create_flow():
    return ResponseBuilder.success(FlowController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/flows/<flow_uuid>', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def get_flow(flow_uuid):
    return ResponseBuilder.success(FlowController.get(flow_uuid))


@context.route('/flows/<flow_uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('rules', 'update')
@map_errors
def update_flow(flow_uuid):
    return ResponseBuilder.success(FlowController.update(flow_uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/flows/<flow_uuid>', methods=('DELETE',))
@login_required
@permission_required('rules', 'delete')
@map_errors
def delete_flow(flow_uuid):
    FlowController.delete(flow_uuid)
    return ResponseBuilder.success()


@context.route('/flows/<flow_uuid>/enable', methods=('POST',))
@login_required
@permission_required('rules', 'update')
@map_errors
def enable_flow(flow_uuid):
    enabled = (request.get_json(silent=True) or {}).get('enabled', True)
    return ResponseBuilder.success(FlowController.enable(flow_uuid, enabled, g.current_user))


@context.route('/flows/<flow_uuid>/run', methods=('POST',))
@login_required
@permission_required('rules', 'update')
@map_errors
def run_flow(flow_uuid):
    return ResponseBuilder.success(FlowController.run(flow_uuid, request.get_json(silent=True) or {}))


@context.route('/flows/<flow_uuid>/runs', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def flow_runs(flow_uuid):
    return ResponseBuilder.success(FlowController.runs(flow_uuid, request.args))


@context.route('/flows/<flow_uuid>/runs/<run_id>', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def flow_run_detail(flow_uuid, run_id):
    return ResponseBuilder.success(FlowController.run_detail(flow_uuid, run_id))
