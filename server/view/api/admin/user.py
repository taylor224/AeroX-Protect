from flask import Blueprint, g, request

from server.controller.user import UserController
from server.decorator import login_required, permission_required
from server.util.pagination import build_page, parse_pagination
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_admin_user', __name__, url_prefix='/api/v1/admin/users')


@context.route('', methods=('GET',))
@login_required
@permission_required('users', 'read')
@map_errors
def list_users():
    p = parse_pagination(request.args)
    total, items = UserController.get_list(p['page'], p['items_per_page'], p['q'], p['sort'], p['order'])
    return ResponseBuilder.success(build_page(items, total, p['page'], p['items_per_page']))


@context.route('', methods=('POST',))
@login_required
@permission_required('users', 'create')
@map_errors
def create_user():
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(UserController.create(data, g.current_user))


@context.route('/<user_uuid>', methods=('GET',))
@login_required
@permission_required('users', 'read')
@map_errors
def get_user(user_uuid):
    return ResponseBuilder.success(UserController.get(user_uuid))


@context.route('/<user_uuid>', methods=('POST',))
@login_required
@permission_required('users', 'update')
@map_errors
def update_user(user_uuid):
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(UserController.update(user_uuid, data, g.current_user))


@context.route('/<user_uuid>', methods=('DELETE',))
@login_required
@permission_required('users', 'delete')
@map_errors
def delete_user(user_uuid):
    UserController.delete(user_uuid, g.current_user)
    return ResponseBuilder.success()


@context.route('/<user_uuid>/reset_password', methods=('POST',))
@login_required
@permission_required('users', 'update')
@map_errors
def reset_password(user_uuid):
    data = request.get_json(silent=True) or {}
    UserController.reset_password(user_uuid, data.get('password'), g.current_user)
    return ResponseBuilder.success()


@context.route('/<user_uuid>/unlock', methods=('POST',))
@login_required
@permission_required('users', 'update')
@map_errors
def unlock(user_uuid):
    UserController.unlock(user_uuid, g.current_user)
    return ResponseBuilder.success()
