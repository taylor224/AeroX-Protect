"""detection.ts → P2 segment mapping (PLAN P4 §5.6). Ingest links eagerly; segments
indexed late leave detection.segment_id NULL → the detection_linker beat backfills."""
import logging

from server.model.detection import Detection
from server.model.segment import Segment

logger = logging.getLogger(__name__)


def link_one(detection: Detection) -> bool:
    seg = Segment.get_at(detection.camera_id, detection.ts)
    if not seg:
        return False
    Detection.link_segment([detection.id], seg.id)
    return True


def backfill(limit: int = 500) -> int:
    linked = 0
    for d in Detection.backfill_candidates(limit):
        if link_one(d):
            linked += 1
    return linked
