from flask import Blueprint, g, request

from server.controller.feature_flag import FeatureFlagController
from server.decorator import login_required, permission_required
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_feature_flag', __name__, url_prefix='/api/v1/feature-flags')


@context.route('', methods=('GET',))
@login_required
@map_errors
def list_flags():
    # readable by any authed user so the SPA can gate UI; no secrets in flags
    return ResponseBuilder.success(FeatureFlagController.list_flags())


@context.route('/<key>', methods=('PUT', 'POST'))
@login_required
@permission_required('feature_flags', 'manage')
@map_errors
def set_flag(key):
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(FeatureFlagController.set_flag(key, data, g.current_user))
