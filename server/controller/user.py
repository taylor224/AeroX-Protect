from server.exception import ConflictException, InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import db
from server.model.audit_log import ACTION_USER_CREATED, ACTION_USER_DELETED, ACTION_USER_UPDATED, AuditLog
from server.model.role import Role
from server.model.user import User
from server.service.permission import PermissionService
from server.service.token import TokenService


class UserController:
    @classmethod
    def get_list(cls, page, items_per_page, q, sort, order) -> tuple[int, list[dict]]:
        total, rows = User.get_list(page, items_per_page, q, sort, order)
        return total, [u.to_dict() for u in rows]

    @classmethod
    def get(cls, user_uuid: str) -> dict:
        return User.get_by_uuid(user_uuid).to_dict()

    @classmethod
    def create(cls, data: dict, actor: User) -> dict:
        login_id = (data.get('login_id') or '').strip()
        password = data.get('password') or ''
        name = (data.get('name') or '').strip()
        if not login_id or not password or not name:
            raise InvalidParameterException('login_id, password, name 은 필수입니다.')
        if len(password) < 8:
            raise InvalidParameterException('비밀번호는 8자 이상이어야 합니다.')
        if User.get_by_login_id(login_id) is not None:
            raise ConflictException('이미 존재하는 아이디입니다.')

        role = cls._resolve_role(data.get('role'))
        cls._guard_grant(actor, role=role, permissions=data.get('permissions'))
        from server.model.setting import Setting
        default_lang = Setting.get_value('default_language', 'ko') or 'ko'
        user = User.create(
            login_id=login_id, password=password, name=name, role_id=role.id,
            email=data.get('email'), phone_number=data.get('phone_number'),
            permissions=data.get('permissions') or {}, language=data.get('language') or default_lang,
            created_by_id=actor.id,
        )
        AuditLog.record(ACTION_USER_CREATED, target=user.uuid, user_id=actor.id,
                        detail={'login_id': login_id, 'role': role.name})
        return user.to_dict()

    @classmethod
    def update(cls, user_uuid: str, data: dict, actor: User) -> dict:
        user = User.get_by_uuid(user_uuid)
        cls._guard_target(actor, user)
        role = None
        role_id = None
        if data.get('role'):
            role = cls._resolve_role(data['role'])
            role_id = role.id
        if role is not None or data.get('permissions') is not None:
            cls._guard_grant(actor, role=role, permissions=data.get('permissions'))

        # guard: don't let the last admin lose admin / be deactivated
        if user.role and user.role.name == 'admin':
            losing_admin = (role_id is not None and role_id != user.role_id) or (data.get('is_active') is False)
            if losing_admin and cls._active_admin_count() <= 1:
                raise InvalidParameterException('마지막 관리자는 변경할 수 없습니다.')

        user.modify(
            name=data.get('name'), email=data.get('email'), phone_number=data.get('phone_number'),
            role_id=role_id, permissions=data.get('permissions'),
            is_active=data.get('is_active'), language=data.get('language'),
            updated_by_id=actor.id,
        )
        AuditLog.record(ACTION_USER_UPDATED, target=user.uuid, user_id=actor.id)
        return user.to_dict()

    @classmethod
    def delete(cls, user_uuid: str, actor: User):
        user = User.get_by_uuid(user_uuid)
        cls._guard_target(actor, user)
        if user.id == actor.id:
            raise InvalidParameterException('본인 계정은 삭제할 수 없습니다.')
        if user.role and user.role.name == 'admin' and cls._active_admin_count() <= 1:
            raise InvalidParameterException('마지막 관리자는 삭제할 수 없습니다.')
        user.soft_delete(deleted_by_id=actor.id)
        TokenService.revoke_all(user)
        AuditLog.record(ACTION_USER_DELETED, target=user.uuid, user_id=actor.id)

    @classmethod
    def reset_password(cls, user_uuid: str, new_password: str, actor: User):
        if not new_password or len(new_password) < 8:
            raise InvalidParameterException('비밀번호는 8자 이상이어야 합니다.')
        user = User.get_by_uuid(user_uuid)
        cls._guard_target(actor, user)
        user.set_password(new_password)
        db.session.add(user)
        db.session.commit()
        TokenService.revoke_all(user)  # invalidate the target's existing tokens
        AuditLog.record(ACTION_USER_UPDATED, target=user.uuid, user_id=actor.id,
                        detail={'action': 'reset_password'})

    @classmethod
    def unlock(cls, user_uuid: str, actor: User):
        user = User.get_by_uuid(user_uuid)
        user.unlock()
        AuditLog.record(ACTION_USER_UPDATED, target=user.uuid, user_id=actor.id,
                        detail={'action': 'unlock'})

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _guard_target(actor: User, target: User):
        """A non-superuser must not manage (edit/delete/reset) a superuser account."""
        if actor.id == target.id:
            return
        if not PermissionService.is_superuser(actor) and PermissionService.is_superuser(target):
            raise NoPermissionException()

    @staticmethod
    def _guard_grant(actor: User, role: Role | None = None, permissions: dict | None = None):
        """Escalation guard: a non-superuser may only grant a role / per-user
        permission map whose entries are a subset of their own effective permissions."""
        if PermissionService.is_superuser(actor):
            return
        sources = []
        if role is not None and isinstance(role.permissions, dict):
            sources.append(role.permissions)
        if permissions is not None:
            if not isinstance(permissions, dict):
                raise InvalidParameterException('permissions 형식이 올바르지 않습니다.')
            sources.append(permissions)
        for source in sources:
            for resource, actions in source.items():
                if isinstance(actions, dict):   # camera_scope / dashboard_scope maps
                    own = PermissionService._merged_scope(actor, resource)
                    for target, granted in actions.items():
                        allowed = set(own.get(target) or own.get('*') or [])
                        if '*' in allowed:
                            continue
                        if not set(granted or ['*']) <= allowed:
                            raise NoPermissionException()
                    continue
                if not isinstance(actions, (list, tuple, set)):
                    continue
                for action in actions:
                    if not PermissionService.has(actor, resource, action):
                        raise NoPermissionException()

    @staticmethod
    def _resolve_role(role_name) -> Role:
        role = Role.get_by_name((role_name or 'user').strip())
        if role is None:
            raise InvalidParameterException('존재하지 않는 역할입니다: %s' % role_name)
        return role

    @staticmethod
    def _active_admin_count() -> int:
        admin = Role.get_by_name('admin')
        if not admin:
            return 0
        return db.session.query(User).filter(
            User.role_id == admin.id, User.is_active.is_(True), User.deleted_at.is_(None)).count()
