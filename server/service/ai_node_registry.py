"""AI node registry (PLAN P4 §7.2): join (issue scoped node token), heartbeat (status/load),
state transitions (online↔degraded↔offline), capacity from bench. Authority = ai_nodes +
detection_assignments; nodes are stateless executors."""
import logging

from server.model import utcnow
from server.model.ai_node import STATUS_DEGRADED, STATUS_OFFLINE, STATUS_ONLINE, AiNode
from server.service.token import TokenService

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 5


def join(node_id: int, payload: dict, ip: str | None = None) -> dict | None:
    """Confirm a pre-registered node, record its capabilities, and issue a node token."""
    node = AiNode.get_by_id(node_id)
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
        gpu=bool(payload.get('gpu', node.gpu)),
        gpu_name=payload.get('gpu_name'),
        capabilities=payload.get('capabilities'),
        bench=payload.get('bench'),
        version=payload.get('version'),
        capacity=_capacity(payload),
        status=STATUS_ONLINE,
        last_heartbeat_ts=utcnow(),
        last_seen_ip=ip,
        last_error=None,
        token_jti=tok['jti'],
    )
    from server.service import ai_scheduler
    ai_scheduler.rebalance()       # bring the new node into the pool
    return {
        'node_id': str(node.id),
        'node_token': tok['token'],
        'heartbeat_interval_s': HEARTBEAT_INTERVAL_S,
        'assignments_etag': ai_scheduler.current_etag(),
    }


def heartbeat(node: AiNode, payload: dict, ip: str | None = None) -> dict:
    """Update liveness/load. Returns the current etag + drain flag."""
    from server.model.ai_node import STATUS_DRAINING
    status = node.status
    if status not in (STATUS_DRAINING,):
        status = payload.get('status') or STATUS_ONLINE
        if status not in (STATUS_ONLINE, STATUS_DEGRADED):
            status = STATUS_ONLINE
    node.update(status=status, last_heartbeat_ts=utcnow(), last_seen_ip=ip)
    from server.service import ai_scheduler
    return {'ok': True, 'assignments_etag': ai_scheduler.current_etag(),
            'drain': node.status == STATUS_DRAINING}


def mark_offline(node: AiNode):
    node.update(status=STATUS_OFFLINE)


def _capacity(payload: dict) -> int:
    """Concurrent-camera capacity from self-reported bench/capabilities (gpu-weighted default)."""
    if payload.get('capacity'):
        return int(payload['capacity'])
    bench = payload.get('bench') or {}
    if bench.get('capacity'):
        return int(bench['capacity'])
    return 6 if payload.get('gpu') else 2
