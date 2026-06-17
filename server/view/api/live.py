"""Live signaling/media proxy (PLAN P1 §5.2, §6.3).

Browsers never reach go2rtc directly — the backend proxies every live request and
enforces JWT + camera scope. Token may arrive as a Bearer header OR `?access_token=`
(a <video> element can't set headers). Paths:
  POST /live/webrtc/<name>     — relay SDP offer→answer to go2rtc /api/webrtc
  GET  /live/mp4/<name>        — low-latency fMP4 stream (works without WebSocket)
  POST /live/ws-ticket/<name>  — issue a short-lived ticket for the nginx→go2rtc MSE WebSocket
  GET  /live/ws-auth           — nginx auth_request target that validates that ticket

The WS-MSE path (ticket + nginx proxy) gives low-latency playback that works from remote
networks WITHOUT TURN; the fMP4 stream remains the universal fallback.
"""
import json

import requests
from flask import Blueprint, Response, request, stream_with_context

import config
from server.model.camera import Camera
from server.model.stream import Stream
from server.service import live_ticket
from server.service.permission import PermissionService
from server.service.token import TokenService
from server.view.response import ResponseBuilder

context = Blueprint('api_live', __name__, url_prefix='/api/v1/live')

WEBRTC_PORT = 8555       # go2rtc webrtc listen port (docker-compose)


def _inject_host_candidate(sdp: str, ip: str, port: int = WEBRTC_PORT) -> str:
    """Add a UDP host ICE candidate for the server's LAN IP to go2rtc's answer SDP.

    go2rtc listens for WebRTC on 0.0.0.0:8555 but only advertises the candidates from its
    static config. On a LAN with no reachable STUN it advertises nothing usable, so ICE never
    connects and every client falls back to MSE. Appending a host candidate pointing at the
    configured LAN IP (where go2rtc is already listening) lets the browser reach it directly —
    the same thing go2rtc's `webrtc.candidates` config does, but driven by a runtime setting
    so no go2rtc restart is needed. Inserted after each ice-pwd line so it lands in the right
    ICE section regardless of BUNDLE layout."""
    crlf = '\r\n' in sdp
    cand = 'a=candidate:1 1 UDP 2130706431 %s %d typ host%s' % (ip, port, '\r' if crlf else '')
    out = []
    for line in sdp.split('\n'):
        out.append(line)
        if line.startswith('a=ice-pwd:'):
            out.append(cand)
    return '\n'.join(out)


def _with_lan_candidate(body: bytes, content_type: str) -> bytes:
    """If a LAN candidate IP is configured, inject it into go2rtc's answer (JSON {sdp} or raw
    SDP). Best-effort — any parse issue returns the original body unchanged."""
    from server.model.setting import Setting
    ip = (Setting.get_value('webrtc_candidate_ip', '') or '').strip()
    if not ip:
        return body
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        return body
    try:
        if text.lstrip().startswith('{'):
            obj = json.loads(text)
            if isinstance(obj, dict) and obj.get('sdp'):
                obj['sdp'] = _inject_host_candidate(obj['sdp'], ip)
                return json.dumps(obj).encode('utf-8')
            return body
        if 'a=ice-pwd:' in text:
            return _inject_host_candidate(text, ip).encode('utf-8')
    except Exception:       # noqa: BLE001 — never break signaling over a munge error
        return body
    return body


def _resolve(go2rtc_name: str):
    """Returns (user, camera) or a ResponseBuilder error response."""
    token = None
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        token = header[7:].strip()
    token = token or request.args.get('access_token')
    if not token:
        return None, ResponseBuilder.no_permission('authentication_required')
    try:
        user, _ = TokenService.verify_access(token)
    except Exception:
        return None, ResponseBuilder.no_permission('invalid_token')

    stream = Stream.get_by_go2rtc_name(go2rtc_name)
    if not stream:
        return None, ResponseBuilder.not_found('stream_not_found')
    try:
        camera = Camera.get_by_id(stream.camera_id)
    except Exception:
        return None, ResponseBuilder.not_found('camera_not_found')

    if not (PermissionService.has(user, 'live', 'read')
            and PermissionService.has_camera_scope(user, camera.uuid, 'view')):
        return None, ResponseBuilder.forbidden('live_scope_denied')
    return (user, camera), None


@context.route('/webrtc/<go2rtc_name>', methods=('POST',))
def webrtc(go2rtc_name):
    ctx, err = _resolve(go2rtc_name)
    if err:
        return err
    try:
        upstream = requests.post(
            '%s/api/webrtc' % config.GO2RTC_URL, params={'src': go2rtc_name},
            data=request.get_data(), timeout=10,
            headers={'Content-Type': request.headers.get('Content-Type', 'application/sdp')})
    except requests.RequestException as e:
        return ResponseBuilder.internal_server_error('go2rtc unreachable: %s' % e)
    content_type = upstream.headers.get('Content-Type', 'application/json')
    body = upstream.content
    if upstream.status_code == 200:
        body = _with_lan_candidate(body, content_type)
    return Response(body, status=upstream.status_code, content_type=content_type)


@context.route('/mp4/<go2rtc_name>', methods=('GET',))
def mp4(go2rtc_name):
    ctx, err = _resolve(go2rtc_name)
    if err:
        return err
    try:
        upstream = requests.get('%s/api/stream.mp4' % config.GO2RTC_URL,
                                params={'src': go2rtc_name}, stream=True, timeout=15)
    except requests.RequestException as e:
        return ResponseBuilder.internal_server_error('go2rtc unreachable: %s' % e)
    if upstream.status_code != 200:
        return ResponseBuilder.not_found('stream_unavailable')
    return Response(
        stream_with_context(upstream.iter_content(chunk_size=8192)),
        content_type=upstream.headers.get('Content-Type', 'video/mp4'))


@context.route('/ws-ticket/<go2rtc_name>', methods=('POST',))
def ws_ticket(go2rtc_name):
    """Issue a short-lived ticket for the MSE WebSocket. JWT + camera scope are enforced
    here; the ticket then stands in for them on the (header-less) WebSocket handshake."""
    ctx, err = _resolve(go2rtc_name)
    if err:
        return err
    return ResponseBuilder.success(live_ticket.issue(go2rtc_name))


@context.route('/ws-auth', methods=('GET',))
def ws_auth():
    """nginx `auth_request` target. A valid ticket → 200 (nginx upgrades to go2rtc), else 403.
    No JWT here: the ticket already proves an earlier scope-checked issue(). The stream name +
    ticket may arrive three ways — direct query args (tests), per-arg headers, or parsed out of
    the original request line forwarded as `X-Original-URI` (the auth_request subrequest does
    not carry the parent's query string, so this is the reliable path in production)."""
    src = request.args.get('src') or request.headers.get('X-Live-Src')
    ticket = request.args.get('ticket') or request.headers.get('X-Live-Ticket')
    if not (src and ticket):
        from urllib.parse import parse_qs, urlsplit
        qs = parse_qs(urlsplit(request.headers.get('X-Original-URI', '')).query)
        src = src or (qs.get('src') or [None])[0]
        ticket = ticket or (qs.get('ticket') or [None])[0]
    if src and ticket and live_ticket.verify(src, ticket):
        return Response('', status=200)
    return Response('', status=403)
