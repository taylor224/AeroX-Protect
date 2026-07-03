"""Encoder-node control API (mirrors ai_ingest). aud=node scoped tokens only — fully
separated from the user permission map. /nodes/join consumes a one-time join token; the
rest use the issued node token (@encode_node_token_required → g.current_encode_node)."""
from flask import Blueprint, Response, g, request

from server.decorator import encode_node_token_required
from server.service import encode_node_registry, encode_scheduler
from server.service.token import TokenService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_encode_ingest', __name__, url_prefix='/api/v1/encode')


@context.route('/nodes/join', methods=('POST',))
@map_errors
def join():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return ResponseBuilder.no_permission('join_token_required')
    try:
        node_id = TokenService.consume_join_token(auth[7:].strip())
    except Exception:
        return ResponseBuilder.no_permission('invalid_join_token')
    result = encode_node_registry.join(node_id, request.get_json(silent=True) or {}, request.remote_addr)
    if result is None:
        return ResponseBuilder.not_found('node_not_found')
    return ResponseBuilder.success(result)


@context.route('/nodes/heartbeat', methods=('POST',))
@encode_node_token_required
@map_errors
def heartbeat():
    return ResponseBuilder.success(
        encode_node_registry.heartbeat(g.current_encode_node, request.get_json(silent=True) or {},
                                       request.remote_addr))


@context.route('/nodes/assignments', methods=('GET',))
@encode_node_token_required
@map_errors
def assignments():
    etag = encode_scheduler.current_etag()
    if request.headers.get('If-None-Match') == etag:
        return Response(status=304, headers={'ETag': etag})
    items = encode_scheduler.assignments_for_node(g.current_encode_node.id)
    return ResponseBuilder.success({'etag': etag, 'items': items})
