"""Camera → encoder-node distribution (mirrors ai_scheduler). Work list = cameras whose
live transcode is needed AND actively watched (live_activity gate — nobody watching ⇒ the
encoder idles too). Greedy bin-packing by node max_sessions, keeping existing assignments
stable; overflow → no row (camera falls back to local go2rtc transcode); every change
bumps epoch + the Redis etag (nodes re-poll) and re-syncs the camera's go2rtc source."""
import logging

import config
from server.model.encode_assignment import STATE_PENDING, STATE_REASSIGNING, EncodeAssignment
from server.model.encoding_node import EncodingNode
from server.service import encode_config_resolver

logger = logging.getLogger(__name__)
ETAG_KEY = '%s:encode:assign:etag' % config.REDIS_KEY_PREFIX
FLAG_KEY = 'encoding_nodes'


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
    """Bump the etag so nodes re-fetch EncodeJobSpecs."""
    _bump_etag()


def _flag_on() -> bool:
    try:
        from server.service.feature_flag import is_enabled
        return is_enabled(FLAG_KEY)
    except Exception:
        return False


def _cameras_needing_encode() -> list[int]:
    """Enabled cameras whose default-live stream needs H.264 transcode AND has a viewer
    within the idle window (idle cameras get no assignment — encoder CPU stays free)."""
    from server.model.camera import Camera
    from server.service import live_activity
    from server.service.go2rtc_sync import live_transcode_enabled
    window = live_activity.idle_window()
    out = []
    for cam in Camera.get_all_enabled():
        stream = encode_config_resolver.default_live_stream(cam)
        if stream is None or not live_transcode_enabled(cam, stream):
            continue
        if not live_activity.is_active(stream.go2rtc_name, window):
            continue
        out.append(cam.id)
    return out


def rebalance() -> dict:
    if not _flag_on():
        # converge to empty: flag off ⇒ everything reverts to local transcode
        removed = 0
        for a in EncodeAssignment.all_rows():
            cid = a.camera_id
            EncodeAssignment.remove_for_camera(cid)
            resync_camera(cid)
            removed += 1
        if removed:
            _bump_etag()
        return {'assigned': 0, 'pending': [], 'pending_count': 0,
                'changed': removed, 'etag': current_etag()}

    cams = _cameras_needing_encode()
    cam_set = set(cams)
    nodes = EncodingNode.schedulable()
    cap = {n.id: max(0, n.max_sessions) for n in nodes}
    existing = {a.camera_id: a for a in EncodeAssignment.all_rows()}
    load = {n.id: 0 for n in nodes}

    plan: dict[int, int] = {}
    # 1) keep current assignment if its node is still schedulable with spare capacity
    for cam in cams:
        a = existing.get(cam)
        if a and a.node_id in cap and load[a.node_id] < cap[a.node_id]:
            plan[cam] = a.node_id
            load[a.node_id] += 1
    # 2) place the rest on the node with the most remaining capacity
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

    changed_cams: list[int] = []
    for cam in cams:
        nid = plan.get(cam)
        a = existing.get(cam)
        if nid is None:                          # over capacity → local transcode (no row)
            if a:
                EncodeAssignment.remove_for_camera(cam)
                changed_cams.append(cam)
            continue
        if a and a.node_id == nid and a.state != STATE_REASSIGNING:
            continue                             # unchanged — keep state/epoch (no flap)
        EncodeAssignment.assign(cam, nid, state=STATE_PENDING)
        changed_cams.append(cam)
    # drop assignments for cameras no longer needing encode (idle/disabled/codec change)
    for cam in list(existing):
        if cam not in cam_set:
            EncodeAssignment.remove_for_camera(cam)
            changed_cams.append(cam)

    for n in nodes:
        if n.assigned_count != load[n.id]:
            n.update(assigned_count=load[n.id])
    if changed_cams:
        _bump_etag()
        for cid in changed_cams:
            resync_camera(cid)

    return {'assigned': len(cams) - len(pending), 'pending': [str(c) for c in pending],
            'pending_count': len(pending), 'changed': len(changed_cams), 'etag': current_etag()}


def _pick(nodes, load, cap) -> int | None:
    best, best_rem = None, 0
    for n in nodes:                              # nodes already max_sessions-desc
        rem = cap[n.id] - load[n.id]
        if rem > best_rem:
            best, best_rem = n.id, rem
    return best


def assignments_for_node(node_id: int) -> list[dict]:
    """EncodeJobSpec[] for cameras currently assigned to a node."""
    specs = []
    for a in EncodeAssignment.for_node(node_id):
        spec = encode_config_resolver.live_job_spec(a.camera_id)
        if spec:
            specs.append(spec)
    return specs


def reassign(node_id: int) -> dict:
    """Node lost/draining — free its cameras then rebalance onto the remaining pool."""
    for a in EncodeAssignment.for_node(node_id):
        a.set_state(STATE_REASSIGNING)
    return rebalance()


def kick(camera_id) -> None:
    """Snappy single-camera path for viewer arrival (live ticket issue): if the camera is
    encode-eligible and unassigned, run a rebalance now instead of waiting for the beat."""
    if not camera_id or not _flag_on():
        return
    try:
        if EncodeAssignment.get_for_camera(int(camera_id)):
            return
        rebalance()
    except Exception as e:   # best-effort — the 10s supervise beat converges anyway
        logger.debug('encode kick failed camera=%s: %s', camera_id, e)


def resync_camera(camera_id: int) -> None:
    """Re-push the camera's go2rtc source + offload companions after its assignment or
    session state changed (this is what actually flips local ↔ node-published source).
    Best-effort — camera_health's periodic full sync converges if this fails."""
    try:
        from server.model.camera import Camera
        from server.service import go2rtc_sync
        cam = Camera.get_by_id(camera_id)
        if cam:
            go2rtc_sync.sync_camera(cam)
    except Exception as e:
        logger.debug('encode resync failed camera=%s: %s', camera_id, e)
