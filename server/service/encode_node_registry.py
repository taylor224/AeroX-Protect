"""Encoder node registry: join (issue scoped node token), heartbeat (liveness + running
sessions), state transitions (online↔degraded↔offline). Authority = encoding_nodes +
encode_assignments; nodes are stateless executors (mirrors ai_node_registry)."""
import logging

from server.model import utcnow
from server.model.encode_assignment import STATE_ACTIVE, EncodeAssignment
from server.model.encoding_node import STATUS_DEGRADED, STATUS_OFFLINE, STATUS_ONLINE, EncodingNode
from server.service.token import TokenService

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 5
DEFAULT_MAX_SESSIONS = 4
ENCODER_PORT = 8098


def join(node_id: int, payload: dict, ip: str | None = None) -> dict | None:
    """Confirm a pre-registered node, record its capabilities, and issue a node token."""
    node = EncodingNode.get_by_id(node_id)
    if node is None:
        return None
    # revoke a superseded token (rotation) before issuing a new one
    if node.token_jti:
        try:
            TokenService.revoke(node.token_jti, 60)
        except Exception:
            pass
    tok = TokenService.issue_node_token(node.uuid)
    node.update(
        name=payload.get('name') or node.name,
        hwaccel=payload.get('hwaccel'),
        capabilities=payload.get('capabilities'),
        bench=payload.get('bench'),
        version=payload.get('version'),
        max_sessions=_max_sessions(payload),
        endpoint=_endpoint(payload, node, ip),
        status=STATUS_ONLINE,
        last_heartbeat_ts=utcnow(),
        last_seen_ip=ip,
        last_error=None,
        token_jti=tok['jti'],
    )
    from server.service import encode_scheduler
    encode_scheduler.rebalance()       # bring the new node into the pool
    return {
        'node_id': str(node.id),
        'node_token': tok['token'],
        'heartbeat_interval_s': HEARTBEAT_INTERVAL_S,
        'assignments_etag': encode_scheduler.current_etag(),
    }


def heartbeat(node: EncodingNode, payload: dict, ip: str | None = None) -> dict:
    """Update liveness + confirm running encode sessions. A confirmed session flips its
    assignment pending→active, which is what switches the camera's go2rtc source from the
    local ffmpeg transcode to the node-published stream (seamless handover)."""
    from server.model.encoding_node import STATUS_DRAINING
    status = node.status
    if status not in (STATUS_DRAINING,):
        status = payload.get('status') or STATUS_ONLINE
        if status not in (STATUS_ONLINE, STATUS_DEGRADED):
            status = STATUS_ONLINE
    fields = {'status': status, 'last_heartbeat_ts': utcnow(), 'last_seen_ip': ip}
    if payload.get('endpoint'):
        fields['endpoint'] = payload['endpoint']
    node.update(**fields)

    flipped = []
    for cid in payload.get('active_sessions') or []:
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            continue
        a = EncodeAssignment.get_for_camera(cid)
        if a and a.node_id == node.id:
            newly = a.state != STATE_ACTIVE
            EncodeAssignment.mark_report(cid)
            if newly:
                flipped.append(cid)
    from server.service import encode_scheduler
    for cid in flipped:
        encode_scheduler.resync_camera(cid)
    return {'ok': True, 'assignments_etag': encode_scheduler.current_etag(),
            'drain': node.status == STATUS_DRAINING}


def mark_offline(node: EncodingNode):
    node.update(status=STATUS_OFFLINE)


def _max_sessions(payload: dict) -> int:
    if payload.get('max_sessions'):
        return int(payload['max_sessions'])
    bench = payload.get('bench') or {}
    if bench.get('max_sessions'):
        return int(bench['max_sessions'])
    return DEFAULT_MAX_SESSIONS


def _endpoint(payload: dict, node: EncodingNode, ip: str | None) -> str | None:
    """Node's reachable URL for playback POST /transcode: self-advertised, else the
    admin-set value, else derived from the join source IP."""
    if payload.get('endpoint'):
        return payload['endpoint']
    if node.endpoint:
        return node.endpoint
    return 'http://%s:%d' % (ip, ENCODER_PORT) if ip else None
