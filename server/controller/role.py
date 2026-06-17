from server.exception import ConflictException, InvalidParameterException
from server.model import db, utcnow
from server.model.audit_log import ACTION_ROLE_UPDATED, AuditLog
from server.model.permission import Permission
from server.model.role import Role
from server.model.user import User


class RoleController:
    @classmethod
    def get_list(cls) -> list[dict]:
        return [r.to_dict() for r in Role.get_all()]

    @classmethod
    def get_permission_catalog(cls) -> list[dict]:
        return [p.to_dict() for p in Permission.get_all()]

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        name = (data.get('name') or '').strip()
        display_name = (data.get('display_name') or '').strip()
        if not name or not display_name:
            raise InvalidParameterException('name, display_name 은 필수입니다.')
        if Role.get_by_name(name) is not None:
            raise ConflictException('이미 존재하는 역할입니다.')

        permissions = cls._validate_permissions(data.get('permissions') or {})
        role = Role()
        role.name = name
        role.display_name = display_name
        role.description = data.get('description')
        role.permissions = permissions
        role.is_system = False
        role.created_by_id = actor.id
        role.last_updated_by_id = actor.id
        db.session.add(role)
        db.session.commit()
        AuditLog.record(ACTION_ROLE_UPDATED, target=name, user_id=actor.id, detail={'action': 'create'})
        return role.to_dict()

    @classmethod
    def update(cls, role_id: int, data: dict, actor) -> dict:
        role = Role.get_by_id(role_id)

        # system roles: permissions editable, name immutable
        if not role.is_system and data.get('name'):
            new_name = data['name'].strip()
            if new_name != role.name and Role.get_by_name(new_name) is not None:
                raise ConflictException('이미 존재하는 역할 이름입니다.')
            role.name = new_name

        if data.get('display_name'):
            role.display_name = data['display_name'].strip()
        if 'description' in data:
            role.description = data.get('description')
        if 'permissions' in data:
            role.permissions = cls._validate_permissions(data.get('permissions') or {})

        role.last_updated_by_id = actor.id
        db.session.add(role)
        db.session.commit()
        AuditLog.record(ACTION_ROLE_UPDATED, target=role.name, user_id=actor.id)
        return role.to_dict()

    @classmethod
    def delete(cls, role_id: int, actor) -> None:
        role = Role.get_by_id(role_id)                 # raises RowNotFound if missing/deleted
        if role.is_system:
            raise InvalidParameterException('시스템 역할은 삭제할 수 없습니다.')
        in_use = db.session.query(User).filter(
            User.role_id == role.id, User.deleted_at.is_(None)).count()
        if in_use:
            raise ConflictException('이 역할을 사용 중인 사용자가 %d명 있습니다.' % in_use)
        role.deleted_at = utcnow()
        role.last_updated_by_id = actor.id
        db.session.add(role)
        db.session.commit()
        AuditLog.record(ACTION_ROLE_UPDATED, target=role.name, user_id=actor.id, detail={'action': 'delete'})

    @staticmethod
    def _validate_permissions(permissions: dict) -> dict:
        """Reject permission keys/actions not in the catalog (`*` wildcard allowed)."""
        if not isinstance(permissions, dict):
            raise InvalidParameterException('permissions 형식이 올바르지 않습니다.')
        catalog = {}
        for p in Permission.get_all():
            catalog.setdefault(p.resource, set()).add(p.action)

        for resource, actions in permissions.items():
            if resource == '*':
                continue
            if not isinstance(actions, list):
                raise InvalidParameterException('permissions[%s] 는 리스트여야 합니다.' % resource)
            if resource not in catalog:
                raise InvalidParameterException('알 수 없는 권한 자원: %s' % resource)
            for action in actions:
                if action != '*' and action not in catalog[resource]:
                    raise InvalidParameterException('알 수 없는 권한: %s:%s' % (resource, action))
        return permissions
