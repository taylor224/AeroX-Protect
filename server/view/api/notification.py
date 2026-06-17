from flask import Blueprint, g, request

from server.controller.notification import NotificationController, PushController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_notification', __name__, url_prefix='/api/v1')


# ── notification center ─────────────────────────────────────────────────────────
@context.route('/notifications', methods=('GET',))
@login_required
@permission_required('notifications', 'read')
@map_errors
def list_notifications():
    return ResponseBuilder.success(NotificationController.list_notifications(g.current_user, request.args))


@context.route('/notifications/<int:notif_id>/read', methods=('POST',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def read_notification(notif_id):
    return ResponseBuilder.success(NotificationController.read(g.current_user, notif_id))


@context.route('/notifications/read-all', methods=('POST',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def read_all():
    return ResponseBuilder.success(NotificationController.read_all(g.current_user))


# ── subscriptions ───────────────────────────────────────────────────────────────
@context.route('/notification-subscriptions', methods=('GET',))
@login_required
@permission_required('notifications', 'read')
@map_errors
def list_subscriptions():
    return ResponseBuilder.success({'items': NotificationController.list_subscriptions(g.current_user)})


@context.route('/notification-subscriptions', methods=('POST',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def create_subscription():
    return ResponseBuilder.success(
        NotificationController.create_subscription(g.current_user, request.get_json(silent=True) or {}))


@context.route('/notification-subscriptions/<int:sub_id>', methods=('PUT', 'POST'))
@login_required
@permission_required('notifications', 'update')
@map_errors
def update_subscription(sub_id):
    return ResponseBuilder.success(
        NotificationController.update_subscription(g.current_user, sub_id, request.get_json(silent=True) or {}))


@context.route('/notification-subscriptions/<int:sub_id>', methods=('DELETE',))
@login_required
@permission_required('notifications', 'update')
@map_errors
def delete_subscription(sub_id):
    NotificationController.delete_subscription(g.current_user, sub_id)
    return ResponseBuilder.success()


# ── web push ────────────────────────────────────────────────────────────────────
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
