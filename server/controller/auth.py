from datetime import timedelta

import config
from server.exception import (
    AccountLockedException,
    AuthenticationException,
    InvalidParameterException,
)
from server.model import utcnow
from server.model.audit_log import (
    ACTION_ACCOUNT_LOCKED,
    ACTION_LOGIN_FAILED,
    ACTION_LOGIN_SUCCESS,
    ACTION_LOGOUT,
    ACTION_PASSWORD_CHANGED,
    ACTION_TOKEN_REFRESH,
    AuditLog,
)
from server.model.user import User
from server.service.permission import PermissionService
from server.service.token import TokenService

# /auth/me menu catalog — (title, icon, path, required resource:action). Filtered by
# effective permissions; admin (`*`) sees all. Phases append items.
MENU_ITEMS = [
    ('menu.live', 'video', '/live', ('live', 'read')),
    ('menu.playback', 'history', '/playback', ('playback', 'read')),
    ('menu.events', 'bell', '/events', ('events', 'read')),
    ('menu.cameras', 'cctv', '/cameras', ('cameras', 'read')),
    ('menu.storage', 'database', '/storage', ('storage', 'read')),
    ('menu.dashboards', 'grid', '/dashboards', ('dashboards', 'read')),
    ('menu.monitors', 'monitor', '/monitors', ('monitors', 'read')),
    ('menu.rules', 'workflow', '/rules', ('rules', 'read')),
    ('menu.ai', 'sparkles', '/ai', ('ai', 'read')),
    ('menu.users', 'users', '/users', ('users', 'read')),
    ('menu.settings', 'settings', '/settings', ('settings', 'read')),
]


class AuthController:
    @classmethod
    def login(cls, login_id: str, password: str, ip: str, user_agent: str) -> dict:
        if not login_id or not password or not login_id.strip() or not password.strip():
            raise AuthenticationException('invalid_credentials')
        login_id = login_id.strip()

        user = User.get_by_login_id(login_id)

        if user is None:
            AuditLog.record(ACTION_LOGIN_FAILED, target=login_id, ip=ip, user_agent=user_agent,
                            detail={'reason': 'unknown_login_id'})
            raise AuthenticationException('invalid_credentials')

        if user.is_locked():
            AuditLog.record(ACTION_LOGIN_FAILED, target=login_id, user_id=user.id, ip=ip,
                            user_agent=user_agent, detail={'reason': 'locked'})
            raise AccountLockedException('account_locked')

        if not user.verify_password(password):
            locked = user.register_failed_login(config.LOGIN_MAX_FAILED, config.LOGIN_LOCK_MINUTES)
            AuditLog.record(ACTION_LOGIN_FAILED, target=login_id, user_id=user.id, ip=ip,
                            user_agent=user_agent, detail={'reason': 'bad_password'})
            if locked:
                AuditLog.record(ACTION_ACCOUNT_LOCKED, target=login_id, user_id=user.id, ip=ip,
                                user_agent=user_agent)
                raise AccountLockedException('account_locked')
            raise AuthenticationException('invalid_credentials')

        if not user.is_active:
            raise AuthenticationException('inactive_user')

        user.register_successful_login()
        bundle = TokenService.issue_pair(user, aud='web', user_agent=user_agent, ip=ip)
        AuditLog.record(ACTION_LOGIN_SUCCESS, target=login_id, user_id=user.id, ip=ip,
                        user_agent=user_agent)

        bundle['user'] = cls._user_public(user)
        return bundle

    @classmethod
    def refresh(cls, refresh_token: str, ip: str, user_agent: str) -> dict:
        if not refresh_token:
            raise AuthenticationException('invalid_refresh')
        bundle = TokenService.rotate_refresh(refresh_token, user_agent=user_agent, ip=ip)
        user = bundle.pop('user')
        AuditLog.record(ACTION_TOKEN_REFRESH, target=user.login_id, user_id=user.id, ip=ip,
                        user_agent=user_agent)
        bundle['user'] = cls._user_public(user)
        return bundle

    @classmethod
    def logout(cls, access_claims: dict | None, refresh_jti: str | None, user, ip: str, user_agent: str):
        TokenService.revoke_pair(access_claims, refresh_jti)
        if user is not None:
            AuditLog.record(ACTION_LOGOUT, target=user.login_id, user_id=user.id, ip=ip,
                            user_agent=user_agent)

    @classmethod
    def change_password(cls, user: User, previous_password: str, new_password: str):
        if not previous_password or not new_password:
            raise InvalidParameterException('비밀번호를 입력하세요.')
        if not user.verify_password(previous_password):
            raise InvalidParameterException('이전 비밀번호가 올바르지 않습니다.')
        if len(new_password) < 8:
            raise InvalidParameterException('비밀번호는 8자 이상이어야 합니다.')

        user.set_password(new_password)
        from server.model import db
        db.session.add(user)
        db.session.commit()
        # invalidate all existing sessions/tokens (force re-login elsewhere)
        TokenService.revoke_all(user)
        AuditLog.record(ACTION_PASSWORD_CHANGED, target=user.login_id, user_id=user.id)

    @classmethod
    def set_language(cls, user: User, language: str) -> str:
        if language not in ('ko', 'en'):
            raise InvalidParameterException('지원하지 않는 언어입니다.')
        user.modify(language=language, updated_by_id=user.id)
        return language

    @classmethod
    def me(cls, user: User) -> dict:
        permissions = PermissionService.effective_permissions(user)
        return {
            'user': cls._user_public(user),
            'permissions': permissions,
            'menus': cls._menus_for(user),
        }

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _user_public(user: User) -> dict:
        return {
            'uuid': user.uuid,
            'login_id': user.login_id,
            'name': user.name,
            'email': user.email,
            'role': user.role.name if user.role else None,
            'language': user.language or 'ko',
            'permissions': PermissionService.effective_permissions(user),
        }

    @staticmethod
    def _menus_for(user: User) -> list[dict]:
        menus = []
        for title, icon, path, (resource, action) in MENU_ITEMS:
            if PermissionService.has(user, resource, action):
                menus.append({'title': title, 'icon': icon, 'path': path})
        return menus
