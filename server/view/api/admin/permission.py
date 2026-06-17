from flask import Blueprint

from server.controller.role import RoleController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_admin_permission', __name__, url_prefix='/api/v1/admin/permissions')


@context.route('', methods=('GET',))
@login_required
@permission_required('users', 'read')
@map_errors
def list_permissions():
    """Permission catalog — powers the frontend role permission editor."""
    return ResponseBuilder.success(RoleController.get_permission_catalog())
