"""AI node health sweep + rebalance (PLAN P4 §7.4). Marks nodes whose heartbeat went
stale offline, then rebalances (offline nodes' cameras reassign; pending placed)."""
import logging
from datetime import timedelta

from server.model import utcnow
from server.model.ai_node import AiNode
from server.service import ai_node_registry, ai_scheduler
from server.service.ai_node_registry import HEARTBEAT_INTERVAL_S
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)
NODE_STALE_S = 3 * HEARTBEAT_INTERVAL_S       # miss ~3 heartbeats → offline


@app.task(name='server.task.list.ai_supervise.supervise_nodes')
@celery_use_db()
def supervise_nodes():
    cutoff = utcnow() - timedelta(seconds=NODE_STALE_S)
    stale = AiNode.stale(cutoff)
    for n in stale:
        ai_node_registry.mark_offline(n)
        logger.info('ai_supervise: node %s offline (stale heartbeat)', n.id)
    result = ai_scheduler.rebalance()
    return {'offlined': len(stale), **result}
