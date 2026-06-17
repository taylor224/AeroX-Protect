from server.exception import InvalidParameterException, RowNotFoundException
from server.model.camera import Camera
from server.model.object_trigger import ObjectTrigger
from server.service import ai_scheduler


def _resolve_camera_id(camera_uuid):
    if not camera_uuid:
        return None
    return Camera.get_by_uuid(camera_uuid).id


class ObjectTriggerController:
    @classmethod
    def list_triggers(cls, camera_uuid) -> list[dict]:
        return [t.to_dict() for t in ObjectTrigger.list_for(_resolve_camera_id(camera_uuid))]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        cls._validate(data)
        if data.get('camera_uuid'):
            data['camera_id'] = Camera.get_by_uuid(data['camera_uuid']).id
        t = ObjectTrigger.create(data, actor.id)
        ai_scheduler.touch()
        return t.to_dict()

    @classmethod
    def update(cls, trigger_id: int, data: dict, actor) -> dict:
        t = ObjectTrigger.get_by_id(trigger_id)
        if not t:
            raise RowNotFoundException()
        if 'labels' in data:
            cls._validate({**t.to_dict(), **data})
        t.modify(data, actor.id)
        ai_scheduler.touch()
        return t.to_dict()

    @classmethod
    def delete(cls, trigger_id: int):
        t = ObjectTrigger.get_by_id(trigger_id)
        if not t:
            raise RowNotFoundException()
        t.soft_delete()
        ai_scheduler.touch()

    @classmethod
    def test(cls, data: dict) -> dict:
        """Match preview (no firing). Returns {matched, trigger_id?, would_action?}."""
        camera_id = _resolve_camera_id(data.get('camera_uuid')) or (
            int(data['camera_id']) if data.get('camera_id') else None)
        if camera_id is None:
            raise InvalidParameterException('camera required')
        label = data.get('label')
        conf = int(data.get('confidence') or 0)
        if conf <= 1 and isinstance(data.get('confidence'), float):
            conf = int(conf * 100)
        zone_id = int(data['zone_id']) if data.get('zone_id') else None
        for t in ObjectTrigger.get_candidates(camera_id):
            if label not in (t.labels or []):
                continue
            if conf < t.min_confidence:
                continue
            if t.zone_id is not None and (zone_id is None or int(t.zone_id) != zone_id):
                continue
            return {'matched': True, 'trigger_id': str(t.id), 'name': t.name,
                    'would_action': t.action_hint or 'event', 'event_subtype': t.event_subtype or label}
        return {'matched': False}

    @staticmethod
    def _validate(data):
        labels = data.get('labels')
        if not isinstance(labels, list) or not labels:
            raise InvalidParameterException('labels must be a non-empty list')
        if not data.get('name'):
            raise InvalidParameterException('name required')
