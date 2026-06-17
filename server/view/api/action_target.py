from flask import Blueprint, g, request

from server.controller.action_target import ActionTargetController
from server.controller.webhook import WebhookController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_action_target', __name__, url_prefix='/api/v1')


# ── action targets (speaker / io / email) ──────────────────────────────────────
@context.route('/action-targets', methods=('GET',))
@login_required
@permission_required('targets', 'read')
@map_errors
def list_targets():
    return ResponseBuilder.success({'items': ActionTargetController.list_targets(request.args.get('type'))})


@context.route('/action-targets', methods=('POST',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def create_target():
    return ResponseBuilder.success(ActionTargetController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/action-targets/<uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('targets', 'manage')
@map_errors
def update_target(uuid):
    return ResponseBuilder.success(ActionTargetController.update(uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/action-targets/<uuid>', methods=('DELETE',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def delete_target(uuid):
    ActionTargetController.delete(uuid)
    return ResponseBuilder.success()


@context.route('/action-targets/<uuid>/test', methods=('POST',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def test_target(uuid):
    return ResponseBuilder.success(ActionTargetController.test(uuid, request.get_json(silent=True) or {}))


@context.route('/action-targets/<uuid>/healthcheck', methods=('POST',))
@login_required
@permission_required('targets', 'read')
@map_errors
def healthcheck_target(uuid):
    return ResponseBuilder.success(ActionTargetController.healthcheck(uuid))


# ── webhooks ────────────────────────────────────────────────────────────────────
@context.route('/webhooks', methods=('GET',))
@login_required
@permission_required('targets', 'read')
@map_errors
def list_webhooks():
    return ResponseBuilder.success({'items': WebhookController.list_webhooks(request.args.get('purpose'))})


@context.route('/webhooks', methods=('POST',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def create_webhook():
    return ResponseBuilder.success(WebhookController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/webhooks/<uuid>', methods=('PUT', 'POST'))
@login_required
@permission_required('targets', 'manage')
@map_errors
def update_webhook(uuid):
    return ResponseBuilder.success(WebhookController.update(uuid, request.get_json(silent=True) or {}, g.current_user))


@context.route('/webhooks/<uuid>', methods=('DELETE',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def delete_webhook(uuid):
    WebhookController.delete(uuid)
    return ResponseBuilder.success()


@context.route('/webhooks/<uuid>/test', methods=('POST',))
@login_required
@permission_required('targets', 'manage')
@map_errors
def test_webhook(uuid):
    return ResponseBuilder.success(WebhookController.test(uuid, request.get_json(silent=True) or {}))
