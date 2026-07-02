from flask import Blueprint, g, request

from server.controller.notification import PushController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_notification', __name__, url_prefix='/api/v1')


# ── web push (consumed by flow `push` action nodes) ─────────────────────────────
@context.route('/push/vapid-public-key', methods=('GET',))
@login_required
@map_errors
def vapid_key():
    return ResponseBuilder.success(PushController.vapid_key())


@context.route('/push/subscriptions', methods=('POST',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def push_subscribe():
    return ResponseBuilder.success(PushController.subscribe(g.current_user, request.get_json(silent=True) or {}))


@context.route('/push/subscriptions', methods=('DELETE',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def push_unsubscribe():
    PushController.unsubscribe(g.current_user, (request.get_json(silent=True) or {}).get('endpoint', ''))
    return ResponseBuilder.success()


@context.route('/push/test', methods=('POST',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def push_test():
    return ResponseBuilder.success(PushController.test(g.current_user))
