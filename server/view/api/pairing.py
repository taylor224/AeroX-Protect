"""Monitor pairing (public claim) + monitor-token endpoints (PLAN P5 §5.3, §7.1)."""
from flask import Blueprint, g, request

from server.controller.monitor import PairingController
from server.decorator import monitor_required
from server.service import pairing_code
from server.service.token import TokenService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_pairing', __name__, url_prefix='/api/v1')


@context.route('/pairing/claim', methods=('POST',))
@map_errors
def claim():
    if not pairing_code.rate_limit_ok(request.remote_addr):
        return ResponseBuilder.too_many_requests('rate_limited')
    code = str((request.get_json(silent=True) or {}).get('code', ''))
    try:
        return ResponseBuilder.success(PairingController.claim(code, request.remote_addr,
                                                               request.user_agent.string))
    except ValueError:
        return ResponseBuilder.bad_request('invalid_or_expired')


@context.route('/monitor/refresh', methods=('POST',))
@map_errors
def refresh():
    token = (request.get_json(silent=True) or {}).get('refresh_token', '')
    try:
        pair = TokenService.rotate_monitor_refresh(token)
    except Exception:
        return ResponseBuilder.no_permission('invalid_refresh')
    return ResponseBuilder.success({'access_token': pair['access_token'], 'refresh_token': pair['refresh_token'],
                                    'token_type': 'Bearer', 'expires_in': pair['expires_in']})


@context.route('/monitor/me', methods=('GET',))
@monitor_required
@map_errors
def monitor_me():
    return ResponseBuilder.success(PairingController.me(g.current_monitor))


@context.route('/monitor/heartbeat', methods=('POST',))
@monitor_required
@map_errors
def monitor_heartbeat():
    return ResponseBuilder.success(PairingController.heartbeat(g.current_monitor))
