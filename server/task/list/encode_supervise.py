"""Encoder node health sweep + rebalance (mirrors ai_supervise). Marks nodes whose
heartbeat went stale offline, then rebalances — which also re-evaluates the live-activity
gate every pass (idle cameras lose their assignment; newly-watched ones gain it)."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.encoding_node import EncodingNode
from server.service import encode_node_registry, encode_scheduler
from server.service.encode_node_registry import HEARTBEAT_INTERVAL_S
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)
NODE_STALE_S = 3 * HEARTBEAT_INTERVAL_S       # miss ~3 heartbeats → offline


@app.task(name='server.task.list.encode_supervise.supervise_encode_nodes')
@celery_use_db()
def supervise_encode_nodes():
    cutoff = utcnow() - timedelta(seconds=NODE_STALE_S)
    stale = EncodingNode.stale(cutoff)
    for n in stale:
        encode_node_registry.mark_offline(n)
        logger.info('encode_supervise: node %s offline (stale heartbeat)', n.id)
    result = encode_scheduler.rebalance()
    return {'offlined': len(stale), **result}
