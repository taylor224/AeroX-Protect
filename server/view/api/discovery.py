from flask import Blueprint, request

from server.controller.discovery import DiscoveryController
from server.decorator import login_required, permission_required
from server.util.tool import safe_int
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_discovery', __name__, url_prefix='/api/v1/discovery')


@context.route('/onvif', methods=('GET',))
@login_required
@permission_required('cameras', 'discover')
@map_errors
def discover_onvif():
    timeout = safe_int(request.args.get('timeout'), 4)
    return ResponseBuilder.success({'devices': DiscoveryController.discover_onvif(timeout)})


@context.route('/probe', methods=('POST',))
@login_required
@permission_required('cameras', 'discover')
@map_errors
def probe():
    data = request.get_json(silent=True) or {}
    return ResponseBuilder.success(DiscoveryController.probe(data))
