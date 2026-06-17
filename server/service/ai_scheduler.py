"""Camera → node distribution (PLAN P4 §7.3–7.4). Greedy bin-packing by node capacity,
keeping existing assignments stable (minimal movement); overflow → pending; every change
bumps epoch (stale-report rejection) and the Redis etag (nodes re-poll). Offline-node
cameras fall through to reassignment automatically (offline node not in the capacity pool)."""
import logging

import config
from server.model.ai_node import AiNode
from server.model.detection_assignment import STATE_PENDING, DetectionAssignment
from server.service import ai_config_resolver

logger = logging.getLogger(__name__)
ETAG_KEY = '%s:ai:assign:etag' % config.REDIS_KEY_PREFIX


def _redis():
    from server.service.token import get_redis
    return get_redis()


def current_etag() -> str:
    try:
        return _redis().get(ETAG_KEY) or '0'
    except Exception:
        return '0'


def _bump_etag():
    try:
        _redis().incr(ETAG_KEY)
    except Exception:
        pass


def touch():
    """Bump the etag so nodes re-fetch CameraJobSpecs (zone/settings/trigger change)."""
    _bump_etag()


def rebalance() -> dict:
    cams = ai_config_resolver.enabled_camera_ids()
    cam_set = set(cams)
    nodes = AiNode.schedulable()
    cap = {n.id: max(0, n.capacity) for n in nodes}
    existing = {a.camera_id: a for a in DetectionAssignment.all_rows()}
    load = {n.id: 0 for n in nodes}

    plan: dict[int, int] = {}
    # 1) keep current assignment if its node is still schedulable with spare capacity
    for cam in cams:
        a = existing.get(cam)
        if a and a.node_id in cap and load[a.node_id] < cap[a.node_id]:
            plan[cam] = a.node_id
            load[a.node_id] += 1
    # 2) place the rest on the node with the most remaining capacity (gpu-first via node order)
    pending = []
    for cam in cams:
        if cam in plan:
            continue
        nid = _pick(nodes, load, cap)
        if nid is None:
            pending.append(cam)
            continue
        plan[cam] = nid
        load[nid] += 1

    changed = 0
    for cam in cams:
        nid = plan.get(cam)
        a = existing.get(cam)
        if nid is None:                          # over capacity → pending (no node row)
            if a:
                DetectionAssignment.remove_for_camera(cam)
                changed += 1
            continue
        if a and a.node_id == nid:
            continue                             # unchanged — keep state/epoch (no flap)
        DetectionAssignment.assign(cam, nid, state=STATE_PENDING)
        changed += 1
    # drop assignments for cameras that are no longer enabled
    for cam in list(existing):
        if cam not in cam_set:
            DetectionAssignment.remove_for_camera(cam)
            changed += 1

    for n in nodes:
        if n.assigned_count != load[n.id]:
            n.update(assigned_count=load[n.id])
    if changed:
        _bump_etag()

    return {'assigned': len(cams) - len(pending), 'pending': [str(c) for c in pending],
            'pending_count': len(pending), 'changed': changed, 'etag': current_etag()}


def _pick(nodes, load, cap) -> int | None:
    best, best_rem = None, 0
    for n in nodes:                              # nodes already gpu-desc, capacity-desc
        rem = cap[n.id] - load[n.id]
        if rem > best_rem:                       # strict > keeps gpu/high-cap first on ties
            best, best_rem = n.id, rem
    return best


def assignments_for_node(node_id: int) -> list[dict]:
    """CameraJobSpec[] for cameras currently assigned to a node."""
    specs = []
    for a in DetectionAssignment.for_node(node_id):
        spec = ai_config_resolver.camera_job_spec(a.camera_id)
        if spec:
            specs.append(spec)
    return specs


def reassign(node_id: int) -> dict:
    """Node lost/draining — free its cameras then rebalance onto the remaining pool."""
    for a in DetectionAssignment.for_node(node_id):
        a.set_state('reassigning')
    return rebalance()
