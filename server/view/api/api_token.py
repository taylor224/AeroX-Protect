from flask import Blueprint, g, request

from server.controller.api_token import ApiTokenController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_api_token', __name__, url_prefix='/api/v1/api-tokens')


@context.route('', methods=('GET',))
@login_required
@permission_required('api_tokens', 'manage')
@map_errors
def list_tokens():
    return ResponseBuilder.success({'items': ApiTokenController.list_tokens()})


@context.route('', methods=('POST',))
@login_required
@permission_required('api_tokens', 'manage')
@map_errors
def create_token():
    return ResponseBuilder.success(ApiTokenController.create(request.get_json(silent=True) or {}, g.current_user))


@context.route('/<uuid>/revoke', methods=('POST',))
@login_required
@permission_required('api_tokens', 'manage')
@map_errors
def revoke_token(uuid):
    return ResponseBuilder.success(ApiTokenController.revoke(uuid))
