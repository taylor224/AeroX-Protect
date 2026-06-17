from server.exception import InvalidParameterException, RowNotFoundException
from server.model.camera import Camera
from server.model.event_policy import ACTIONS, EventPolicy
from server.service import event_policy_resolver, schedule_resolver
from server.service.event_pipeline import combine


def _resolve_camera_id(camera_uuid):
    if not camera_uuid:
        return None
    return Camera.get_by_uuid(camera_uuid).id


class EventPolicyController:
    @classmethod
    def list_policies(cls, camera_uuid) -> list[dict]:
        camera_id = _resolve_camera_id(camera_uuid)
        return [p.to_dict() for p in EventPolicy.list_for(camera_id)]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        cls._validate(data)
        if data.get('camera_uuid'):
            data['camera_id'] = Camera.get_by_uuid(data['camera_uuid']).id
        return EventPolicy.create(data, actor.id).to_dict()

    @classmethod
    def update(cls, policy_id: int, data: dict, actor) -> dict:
        policy = EventPolicy.get_by_id(policy_id)
        if not policy:
            raise RowNotFoundException()
        if data.get('action'):
            cls._validate(data)
        return policy.modify(data, actor.id).to_dict()

    @classmethod
    def delete(cls, policy_id: int):
        policy = EventPolicy.get_by_id(policy_id)
        if not policy:
            raise RowNotFoundException()
        policy.soft_delete()

    @classmethod
    def resolve_preview(cls, data: dict) -> dict:
        from datetime import datetime

        from server.model import UTC, utcnow
        camera_id = Camera.get_by_uuid(data['camera_uuid']).id if data.get('camera_uuid') else int(data['camera_id'])
        event_type = data.get('type')
        subtype = data.get('subtype')
        at_ts = utcnow()
        if data.get('at_ts'):
            at_ts = datetime.fromtimestamp(int(data['at_ts']) / 1000, UTC).replace(tzinfo=None)
        policy = event_policy_resolver.resolve(camera_id, event_type, subtype, at_ts)
        sched_mode = schedule_resolver.mode(camera_id, at_ts)
        if not policy:
            return {'action': 'discard', 'schedule_mode': sched_mode, 'effective_source': None}
        return {
            'action': combine(policy.action, sched_mode, event_type),
            'pre': policy.pre_buffer_s, 'post': policy.post_buffer_s,
            'schedule_mode': sched_mode,
            'effective_source': 'camera' if policy.camera_id else 'global',
        }

    @staticmethod
    def _validate(data):
        if data.get('action') not in ACTIONS:
            raise InvalidParameterException('action must be one of %s' % (ACTIONS,))
        if not data.get('event_type'):
            raise InvalidParameterException('event_type required')
