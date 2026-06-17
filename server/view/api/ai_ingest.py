"""Node report/control API (PLAN P4 §5.2). aud=node scoped tokens only — fully separated
from the user permission map. /nodes/join consumes a one-time join token; the rest use the
issued node token (@node_token_required → g.current_node)."""
from flask import Blueprint, Response, g, request

from server.decorator import node_token_required
from server.service import (
    ai_node_registry, ai_scheduler, audio_ingest, detection_ingest, face_ingest, lpr_ingest)
from server.service.token import TokenService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_ai_ingest', __name__, url_prefix='/api/v1/ai')


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
    result = ai_node_registry.join(node_id, request.get_json(silent=True) or {}, request.remote_addr)
    if result is None:
        return ResponseBuilder.not_found('node_not_found')
    return ResponseBuilder.success(result)


@context.route('/nodes/heartbeat', methods=('POST',))
@node_token_required
@map_errors
def heartbeat():
    return ResponseBuilder.success(
        ai_node_registry.heartbeat(g.current_node, request.get_json(silent=True) or {}, request.remote_addr))


@context.route('/nodes/assignments', methods=('GET',))
@node_token_required
@map_errors
def assignments():
    etag = ai_scheduler.current_etag()
    if request.headers.get('If-None-Match') == etag:
        return Response(status=304, headers={'ETag': etag})
    items = ai_scheduler.assignments_for_node(g.current_node.id)
    return ResponseBuilder.success({'etag': etag, 'items': items})


@context.route('/ingest/detections', methods=('POST',))
@node_token_required
@map_errors
def ingest_detections():
    body = request.get_json(silent=True) or {}
    result = detection_ingest.ingest_batch(
        g.current_node, body.get('batch', []), body.get('epoch_map'))
    return ResponseBuilder.success(result)


@context.route('/ingest/audio', methods=('POST',))
@node_token_required
@map_errors
def ingest_audio():
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(audio_ingest.ingest_batch(g.current_node, body.get('batch', [])))


@context.route('/ingest/plates', methods=('POST',))
@node_token_required
@map_errors
def ingest_plates():
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(lpr_ingest.ingest_batch(g.current_node, body.get('batch', [])))


@context.route('/ingest/faces', methods=('POST',))
@node_token_required
@map_errors
def ingest_faces():
    body = request.get_json(silent=True) or {}
    return ResponseBuilder.success(face_ingest.ingest_batch(g.current_node, body.get('batch', [])))
