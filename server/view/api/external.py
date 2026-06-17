"""External API (audience=api opaque token) — events/state/subscriptions + bounded SSE
(PLAN P5 §5.3, §7.6). SSE is a short-lived stream (client reconnects); a Redis pub/sub
bridge for true long-poll is a follow-up (§14)."""
import json
import time

from flask import Blueprint, Response, g, request

from server.controller.external import ExternalController, _scoped_camera_ids
from server.decorator import api_token_required
from server.service import api_token as api_token_svc
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_external', __name__, url_prefix='/api/v1/ext')


@context.route('/events', methods=('GET',))
@api_token_required('events:read')
@map_errors
def list_events():
    return ResponseBuilder.success(ExternalController.list_events(g.api_token, request.args))


@context.route('/events/<int:event_id>', methods=('GET',))
@api_token_required('events:read')
@map_errors
def get_event(event_id):
    return ResponseBuilder.success(ExternalController.get_event(g.api_token, event_id))


@context.route('/state', methods=('GET',))
@api_token_required('state:read')
@map_errors
def state():
    return ResponseBuilder.success(ExternalController.state(g.api_token))


@context.route('/cameras', methods=('GET',))
@api_token_required('cameras:read')
@map_errors
def cameras():
    return ResponseBuilder.success({'cameras': ExternalController.state(g.api_token)['cameras']})


@context.route('/subscriptions', methods=('POST',))
@api_token_required('events:read')
@map_errors
def create_subscription():
    return ResponseBuilder.success(
        ExternalController.create_subscription(g.api_token, request.get_json(silent=True) or {}))


@context.route('/subscriptions/<uuid>', methods=('DELETE',))
@api_token_required('events:read')
@map_errors
def delete_subscription(uuid):
    ExternalController.delete_subscription(g.api_token, uuid)
    return ResponseBuilder.success()


@context.route('/stream', methods=('GET',))
@api_token_required('events:read')
@map_errors
def stream():
    token = g.api_token
    requested = [int(c) for c in request.args.getlist('camera_id') if c.isdigit()]
    camera_ids = _scoped_camera_ids(token, requested)
    # camera-scoped token whose requested cameras are all out of scope: empty
    # camera_ids would mean "no filter" downstream — stream nothing instead.
    scope_empty = api_token_svc.allowed_camera_ids(token) is not None and not camera_ids

    def gen():
        from server.model import utcnow
        from server.model.event import Event
        last = utcnow()
        yield ': connected\n\n'
        for _ in range(10):                    # ~10s bounded stream; client reconnects
            time.sleep(1)
            if scope_empty:
                yield ': heartbeat\n\n'
                continue
            _, rows = Event.get_list(camera_ids=camera_ids, start=last, page=1,
                                     items_per_page=20, order='asc')
            for e in rows:
                yield 'data: %s\n\n' % json.dumps(e.to_dict())
            if rows:
                last = utcnow()
            yield ': heartbeat\n\n'

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
