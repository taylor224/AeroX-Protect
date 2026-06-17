from flask import Blueprint, g, request

from server.controller.rule import RuleController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_rule', __name__, url_prefix='/api/v1')


@context.route('/automation/incoming/<token>', methods=('GET', 'POST'))
@map_errors
def incoming_webhook(token):
    """Unauthenticated inbound trigger — the URL's opaque token IS the credential. Fires the
    one incoming_webhook rule bound to it; body/query become the rule context."""
    body = request.get_json(silent=True) if request.method == 'POST' else None
    return ResponseBuilder.success(
        RuleController.fire_incoming(token, body, dict(request.args)))


@context.route('/rules', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def list_rules():
    return ResponseBuilder.success(RuleController.list_rules(request.args))


@context.route('/rules', methods=('POST',))
@login_required
@permission_required('rules', 'create')
@map_errors
def create_rule():
    return ResponseBuilder.success(RuleController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/rules/<rule_uuid>', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def get_rule(rule_uuid):
    return ResponseBuilder.success(RuleController.get(rule_uuid))


@context.route('/rules/<rule_uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('rules', 'update')
@map_errors
def update_rule(rule_uuid):
    return ResponseBuilder.success(RuleController.update(rule_uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/rules/<rule_uuid>', methods=('DELETE',))
@login_required
@permission_required('rules', 'delete')
@map_errors
def delete_rule(rule_uuid):
    RuleController.delete(rule_uuid)
    return ResponseBuilder.success()


@context.route('/rules/<rule_uuid>/enable', methods=('POST',))
@login_required
@permission_required('rules', 'update')
@map_errors
def enable_rule(rule_uuid):
    enabled = (request.get_json(silent=True) or {}).get('enabled', True)
    return ResponseBuilder.success(RuleController.enable(rule_uuid, enabled, g.current_user))


@context.route('/rules/<rule_uuid>/trigger', methods=('POST',))
@login_required
@permission_required('rules', 'update')
@map_errors
def trigger_rule(rule_uuid):
    return ResponseBuilder.success(RuleController.trigger(rule_uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/rules/<rule_uuid>/test', methods=('POST',))
@login_required
@permission_required('rules', 'update')
@map_errors
def test_rule(rule_uuid):
    return ResponseBuilder.success(RuleController.test(rule_uuid, request.get_json(silent=True) or {}))


@context.route('/rules/<rule_uuid>/executions', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def rule_executions(rule_uuid):
    return ResponseBuilder.success(RuleController.executions(rule_uuid, request.args))


@context.route('/rule-executions', methods=('GET',))
@login_required
@permission_required('rules', 'read')
@map_errors
def all_executions():
    return ResponseBuilder.success(RuleController.all_executions(request.args))
