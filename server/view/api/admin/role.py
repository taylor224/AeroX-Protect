from flask import Blueprint, g, request

from server.controller.role import RoleController
from server.decorator import login_required, permission_required, roles_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_admin_role', __name__, url_prefix='/api/v1/admin/roles')


@context.route('', methods=('GET',))
@login_required
@permission_required('users', 'read')
@map_errors
def list_roles():
    return ResponseBuilder.success(RoleController.get_list())


@context.route('', methods=('POST',))
@login_required
@roles_required('admin')
@map_errors
def create_role():
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(RoleController.create(data, g.current_user))


@context.route('/<int:role_id>', methods=('POST',))
@login_required
@roles_required('admin')
@map_errors
def update_role(role_id):
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(RoleController.update(role_id, data, g.current_user))


@context.route('/<int:role_id>', methods=('DELETE',))
@login_required
@roles_required('admin')
@map_errors
def delete_role(role_id):
    RoleController.delete(role_id, g.current_user)
    return ResponseBuilder.success()
