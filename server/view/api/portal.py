from flask import Blueprint, g, request

from server.controller.portal import PortalController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_portal', __name__, url_prefix='/api/v1')


@context.route('/portal/ice-servers', methods=('GET',))
@login_required
@map_errors
def ice_servers():
    return ResponseBuilder.success(PortalController.ice_servers(g.current_user))


@context.route('/portal/config', methods=('GET',))
@login_required
@permission_required('portal', 'manage')
@map_errors
def get_config():
    return ResponseBuilder.success(PortalController.get_config())


@context.route('/portal/config', methods=('PUT', 'POST'))
@login_required
@permission_required('portal', 'manage')
@map_errors
def update_config():
    return ResponseBuilder.success(PortalController.update_config(request.get_json(silent=True) or {}, g.current_user))
