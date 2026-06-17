"""Two-way audio (PLAN P6 L1). Browser sends a WebRTC sendrecv offer (mic out + camera
audio in); the backend gates on `audio:talk` + camera scope + the camera's `two_way_audio`
capability + a single-speaker lock, then relays the SDP to go2rtc's backchannel. go2rtc
negotiates the camera-side backchannel (ONVIF/vendor) when the source supports it."""
import requests
from flask import Blueprint, Response, g, request

import config
from server.decorator import login_required, permission_required
from server.model.camera import Camera
from server.model.stream import Stream
from server.service import feature_flag, talk_session
from server.service.permission import PermissionService
from server.view.errors import map_errors
from server.view.response import ResponseBuilder

context = Blueprint('api_talk', __name__, url_prefix='/api/v1/cameras')


def _talk_stream_name(camera) -> str | None:
    streams = Stream.get_by_camera(camera.id)
    main = next((s for s in streams if s.role == 'main'), None) or (streams[0] if streams else None)
    return main.go2rtc_name if main else None


@context.route('/<uuid>/talk/offer', methods=('POST',))
@login_required
@permission_required('audio', 'talk')
@map_errors
def talk_offer(uuid):
    if not feature_flag.is_enabled('two_way_audio'):
        return ResponseBuilder.forbidden('feature_disabled')
    camera = Camera.get_by_uuid(uuid)                      # raises → 404
    if not PermissionService.has_camera_scope(g.current_user, camera.uuid, 'view'):
        return ResponseBuilder.forbidden('camera_scope_denied')
    if not camera.two_way_audio:
        return ResponseBuilder.bad_request('two_way_audio_unsupported')

    if not talk_session.acquire(camera.id, g.current_user.id):
        return ResponseBuilder.too_many_requests('talk_busy')   # someone else is speaking

    name = _talk_stream_name(camera)
    if not name:
        talk_session.release(camera.id, g.current_user.id)
        return ResponseBuilder.not_found('stream_not_found')

    try:
        upstream = requests.post(
            '%s/api/webrtc' % config.GO2RTC_URL, params={'src': name},
            data=request.get_data(), timeout=10,
            headers={'Content-Type': request.headers.get('Content-Type', 'application/sdp')})
    except requests.RequestException as e:
        talk_session.release(camera.id, g.current_user.id)
        return ResponseBuilder.internal_server_error('go2rtc unreachable: %s' % e)
    return Response(upstream.content, status=upstream.status_code,
                    content_type=upstream.headers.get('Content-Type', 'application/json'))


@context.route('/<uuid>/talk/stop', methods=('POST',))
@login_required
@permission_required('audio', 'talk')
@map_errors
def talk_stop(uuid):
    camera = Camera.get_by_uuid(uuid)
    talk_session.release(camera.id, g.current_user.id)
    return ResponseBuilder.success()
