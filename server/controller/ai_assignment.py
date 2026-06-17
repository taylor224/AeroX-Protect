from server.exception import InvalidParameterException, RowNotFoundException
from server.model.ai_node import AiNode
from server.model.camera import Camera
from server.model.detection_assignment import STATE_PENDING, DetectionAssignment
from server.service import ai_scheduler


class AiAssignmentController:
    @classmethod
    def list_assignments(cls) -> dict:
        nodes = {n.id: n.name for n in AiNode.list_all()}
        rows = []
        for a in DetectionAssignment.all_rows():
            d = a.to_dict()
            d['node_name'] = nodes.get(a.node_id)
            rows.append(d)
        return {'items': rows, 'etag': ai_scheduler.current_etag()}

    @classmethod
    def rebalance(cls) -> dict:
        return ai_scheduler.rebalance()

    @classmethod
    def pin(cls, camera_id: int, node_id: int) -> dict:
        if not Camera.get_by_id(camera_id):
            raise RowNotFoundException()
        if not AiNode.get_by_id(node_id):
            raise InvalidParameterException('unknown node')
        a = DetectionAssignment.assign(camera_id, node_id, state=STATE_PENDING)
        ai_scheduler.touch()
        return a.to_dict()
