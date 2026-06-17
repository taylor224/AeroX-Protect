from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.api_token import ApiToken
from server.service.permission import PermissionService


class ApiTokenController:
    @classmethod
    def list_tokens(cls) -> list[dict]:
        return [t.to_dict() for t in ApiToken.list_all()]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        if not data.get('name'):
            raise InvalidParameterException('name required')
        scopes = data.get('scopes') or {}
        if not isinstance(scopes, dict) or not scopes:
            raise InvalidParameterException('scopes required (e.g. {"events":["read"]})')
        for resource, actions in scopes.items():
            if not isinstance(resource, str) or not isinstance(actions, (list, tuple)) \
                    or not all(isinstance(a, str) for a in actions):
                raise InvalidParameterException('invalid scopes shape (resource -> [actions])')
            # escalation guard: a non-superuser can only delegate what they hold
            if not PermissionService.is_superuser(actor):
                for action in actions:
                    if not PermissionService.has(actor, resource, action):
                        raise NoPermissionException()
        expires = None
        if data.get('expires_at'):
            expires = datetime.fromtimestamp(int(data['expires_at']) / 1000, UTC).replace(tzinfo=None)
        token, raw = ApiToken.issue(data['name'], scopes, camera_ids=data.get('camera_ids'),
                                    expires_at=expires, actor_id=actor.id)
        return {'token': raw, **token.to_dict()}     # plaintext returned ONCE

    @classmethod
    def revoke(cls, uuid: str) -> dict:
        t = ApiToken.get_by_uuid(uuid)
        if not t:
            raise RowNotFoundException()
        t.revoke()
        return t.to_dict()
