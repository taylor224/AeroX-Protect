from flask import Blueprint, g, request

from server.controller.dashboard import DashboardController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_dashboard', __name__, url_prefix='/api/v1/dashboards')


@context.route('', methods=('GET',))
@login_required
@permission_required('dashboards', 'read')
@map_errors
def list_dashboards():
    return ResponseBuilder.success({'items': DashboardController.get_list(g.current_user)})


@context.route('', methods=('POST',))
@login_required
@permission_required('dashboards', 'create')
@map_errors
def create_dashboard():
    return ResponseBuilder.success(DashboardController.create(g.current_user, request.get_json(silent=True) or {}))


@context.route('/<dashboard_uuid>', methods=('GET',))
@login_required
@permission_required('dashboards', 'read')
@map_errors
def get_dashboard(dashboard_uuid):
    return ResponseBuilder.success(DashboardController.get(g.current_user, dashboard_uuid))


@context.route('/<dashboard_uuid>', methods=('POST',))
@login_required
@permission_required('dashboards', 'update')
@map_errors
def update_dashboard(dashboard_uuid):
    return ResponseBuilder.success(
        DashboardController.update(g.current_user, dashboard_uuid, request.get_json(silent=True) or {}))


@context.route('/<dashboard_uuid>', methods=('DELETE',))
@login_required
@permission_required('dashboards', 'delete')
@map_errors
def delete_dashboard(dashboard_uuid):
    DashboardController.delete(g.current_user, dashboard_uuid)
    return ResponseBuilder.success()


@context.route('/<dashboard_uuid>/acl', methods=('POST',))
@login_required
@permission_required('dashboards', 'share')
@map_errors
def set_acl(dashboard_uuid):
    return ResponseBuilder.success(
        DashboardController.set_acl(g.current_user, dashboard_uuid, request.get_json(silent=True) or {}))


@context.route('/<dashboard_uuid>/acl/<user_id>', methods=('DELETE',))
@login_required
@permission_required('dashboards', 'share')
@map_errors
def remove_acl(dashboard_uuid, user_id):
    DashboardController.remove_acl(g.current_user, dashboard_uuid, user_id)
    return ResponseBuilder.success()
