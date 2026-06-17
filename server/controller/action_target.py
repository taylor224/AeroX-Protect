from server.exception import InvalidParameterException, RowNotFoundException
from server.model.action_target import TYPES, ActionTarget


class ActionTargetController:
    @classmethod
    def list_targets(cls, type_filter=None) -> list[dict]:
        return [t.to_dict() for t in ActionTarget.list_for(type_filter)]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        cls._validate(data)
        return ActionTarget.create(data, actor.id).to_dict()

    @classmethod
    def update(cls, uuid: str, data: dict, actor) -> dict:
        return cls._require(uuid).modify(data, actor.id).to_dict()

    @classmethod
    def delete(cls, uuid: str):
        cls._require(uuid).soft_delete()

    @classmethod
    def test(cls, uuid: str, data: dict) -> dict:
        target = cls._require(uuid)
        if target.type == 'speaker':
            from server.driver import speaker
            return speaker.run(target, data)
        if target.type == 'io':
            from server.driver import io as io_drv
            return io_drv.run(target, data)
        from server.driver import email as email_drv
        return email_drv.send_event(target, {'type': 'test', 'camera_id': None, 'ts': None})

    @classmethod
    def healthcheck(cls, uuid: str) -> dict:
        from server.model import utcnow
        target = cls._require(uuid)
        drv = {'speaker': 'speaker', 'io': 'io'}.get(target.type)
        result = {'status': 'unknown'}
        if drv == 'speaker':
            from server.driver import speaker
            result = speaker.healthcheck(target)
        elif drv == 'io':
            from server.driver import io as io_drv
            result = io_drv.healthcheck(target)
        target.modify({}, None)
        target.status = result.get('status', 'unknown')
        target.last_checked_at = utcnow()
        from server.model import db
        db.session.add(target)
        db.session.commit()
        return result

    @staticmethod
    def _require(uuid) -> ActionTarget:
        t = ActionTarget.get_by_uuid(uuid)
        if not t:
            raise RowNotFoundException()
        return t

    @staticmethod
    def _validate(data):
        if data.get('type') not in TYPES:
            raise InvalidParameterException('type must be one of %s' % (TYPES,))
        if not data.get('name') or not data.get('protocol'):
            raise InvalidParameterException('name and protocol required')
