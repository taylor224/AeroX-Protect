"""Encoder-node offload gates + playback segment offload.

- live_offload_target(): drives go2rtc_sync.build_source — the camera's viewer-facing
  stream flips to the node-published `_enc` stream ONLY once the assignment is ACTIVE
  (node confirmed a running session via heartbeat) and the node is online. Until then
  the local go2rtc ffmpeg transcode keeps serving, so handover has no dead air.
- assignment_for(): any-state assignment — gates the `_raw` companion registration
  (the encoder needs the raw pull available before it can start).
- transcode_segment(): body-in/body-out playback offload with strict local fallback —
  it NEVER raises; False means "do it locally".

Flag off ⇒ every gate returns None/False immediately (flag off = cost 0).
"""
import logging
import os

import config

logger = logging.getLogger(__name__)

INFLIGHT_KEY = '%s:encode:inflight:%%s' % config.REDIS_KEY_PREFIX
SEGMENT_MAX_BYTES = 128 * 1024 * 1024   # oversized segment → local fallback
TRANSCODE_TIMEOUT_S = 45


def _flag_on() -> bool:
    try:
        from server.service.feature_flag import is_enabled
        return is_enabled('encoding_nodes')
    except Exception:
        return False


def assignment_for(camera):
    """The camera's encode assignment row (any state), or None when offload does not
    apply (flag off / no default-live stream / transcode not needed)."""
    if not _flag_on():
        return None
    from server.service import encode_config_resolver
    stream = encode_config_resolver.default_live_stream(camera)
    if stream is None:
        return None
    from server.service.go2rtc_sync import live_transcode_enabled
    if not live_transcode_enabled(camera, stream):
        return None
    from server.model.encode_assignment import EncodeAssignment
    return EncodeAssignment.get_for_camera(camera.id)


def live_offload_target(camera) -> dict | None:
    """{'enc_name', 'raw_name'} when an ONLINE encoder node actively publishes this
    camera's H.264 live stream; None otherwise (→ local transcode)."""
    a = assignment_for(camera)
    if a is None:
        return None
    from server.model.encode_assignment import STATE_ACTIVE
    if a.state != STATE_ACTIVE:
        return None
    from server.model.encoding_node import STATUS_ONLINE, EncodingNode
    node = EncodingNode.get_by_id(a.node_id)
    if not node or not node.enabled or node.status != STATUS_ONLINE:
        return None
    from server.service import encode_config_resolver
    stream = encode_config_resolver.default_live_stream(camera)
    return {'enc_name': encode_config_resolver.enc_name(stream),
            'raw_name': encode_config_resolver.raw_name(stream)}


# ── playback segment offload ──────────────────────────────────────────────────
def transcode_segment(src_path: str, out_path: str) -> bool:
    """POST the raw segment bytes to the least-loaded online encoder node and write the
    returned H.264 .ts to out_path (atomic replace). False on ANY problem — the caller
    always has the local ffmpeg path as fallback."""
    if not _flag_on():
        return False
    node = _pick_node()
    if node is None:
        return False
    try:
        size = os.path.getsize(src_path)
        if size <= 0 or size > SEGMENT_MAX_BYTES:
            return False
        with open(src_path, 'rb') as f:
            body = f.read()
    except OSError:
        return False

    key = INFLIGHT_KEY % node.id
    r = None
    try:
        from server.service.token import get_redis
        r = get_redis()
        r.incr(key)
        r.expire(key, 120)   # safety: a crashed request never pins the gauge
    except Exception:
        r = None
    try:
        import requests
        resp = requests.post(
            '%s/transcode' % node.endpoint.rstrip('/'), data=body,
            headers={'X-Encode-Secret': config.ENCODE_CALLBACK_SECRET or '',
                     'Content-Type': 'application/octet-stream'},
            timeout=TRANSCODE_TIMEOUT_S)
        if resp.status_code != 200 or not resp.content:
            return False
        tmp = '%s.enc.%d' % (out_path, os.getpid())
        with open(tmp, 'wb') as f:
            f.write(resp.content)
        os.replace(tmp, out_path)   # atomic — same semantics as the local path
        return True
    except Exception as e:
        logger.debug('encode offload failed (falling back local) node=%s: %s', node.id, e)
        return False
    finally:
        if r is not None:
            try:
                r.decr(key)
            except Exception:
                pass


def _pick_node():
    """Least-loaded online node with a reachable endpoint. Playback bursts are counted
    in a separate Redis in-flight gauge so they never distort live-session scheduling."""
    from server.model.encoding_node import EncodingNode
    try:
        nodes = [n for n in EncodingNode.schedulable() if n.endpoint]
    except Exception:
        return None
    if not nodes:
        return None
    best, best_load = None, None
    try:
        from server.service.token import get_redis
        r = get_redis()
    except Exception:
        return nodes[0]
    for n in nodes:
        try:
            inflight = int(r.get(INFLIGHT_KEY % n.id) or 0)
        except Exception:
            inflight = 0
        if inflight >= max(2, (n.max_sessions or 0) * 2):
            continue   # saturated — leave playback to a freer node or local
        if best_load is None or inflight < best_load:
            best, best_load = n, inflight
    return best
