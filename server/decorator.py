"""Auth/RBAC decorators. `before_request` already resolved the JWT into
`g.current_user` (or None); these enforce access.

    @login_required
    @permission_required('cameras', 'read')
    @roles_required('admin')
"""
import functools

from flask import g, request

from server.model.audit_log import ACTION_PERMISSION_DENIED, AuditLog
from server.service.permission import PermissionService
from server.view.response import ResponseBuilder


def login_required(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if g.get('current_user') is None:
            return ResponseBuilder.no_permission('authentication_required')
        return func(*args, **kwargs)
    return wrapper


def permission_required(resource: str, action: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = g.get('current_user')
            if user is None:
                return ResponseBuilder.no_permission('authentication_required')
            if not PermissionService.has(user, resource, action):
                _audit_denied(user, '%s:%s' % (resource, action))
                return ResponseBuilder.forbidden('permission_denied')
            return func(*args, **kwargs)
        return wrapper
    return decorator


def node_token_required(func):
    """Guard for node-report APIs (PLAN P4 §5.2). aud=node scoped token only — fully
    separated from the user permission map. Sets g.current_node."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from server.model.ai_node import AiNode
        from server.service.token import TokenService
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return ResponseBuilder.no_permission('node_auth_required')
        try:
            claims = TokenService.verify_node_token(auth[7:].strip())
        except Exception:
            return ResponseBuilder.no_permission('invalid_node_token')
        node = AiNode.get_by_uuid(claims.get('sub', ''))
        if not node or not node.enabled or node.deleted_at is not None:
            return ResponseBuilder.forbidden('node_disabled')
        if node.token_jti and claims.get('jti') != node.token_jti:
            return ResponseBuilder.forbidden('node_token_superseded')
        g.current_node = node
        return func(*args, **kwargs)
    return wrapper


def api_token_required(*required_scopes: str):
    """Guard for external API (PLAN P5 §5.6). Opaque token (Bearer or X-API-Key), scope +
    rate-limit enforced. Sets g.api_token (camera scope intersection used in controllers)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from server.service import api_token as api_token_svc
            raw = _extract_api_key()
            tok = api_token_svc.verify(raw)
            if not tok:
                return ResponseBuilder.no_permission('invalid_api_token')
            if not api_token_svc.check_rate_limit(tok):
                return ResponseBuilder.too_many_requests('rate_limited')
            for spec in required_scopes:
                resource, _, action = spec.partition(':')
                if not tok.has_scope(resource, action):
                    return ResponseBuilder.forbidden('insufficient_scope')
            tok.touch(request.remote_addr)
            g.api_token = tok
            return func(*args, **kwargs)
        return wrapper
    return decorator


def _extract_api_key():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:].strip()
    return request.headers.get('X-API-Key')


def monitor_required(func):
    """Guard for monitor (kiosk) endpoints. audience=monitor scoped JWT; sets g.current_monitor."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from server.service.token import TokenService
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return ResponseBuilder.no_permission('monitor_auth_required')
        try:
            monitor, claims = TokenService.verify_monitor_access(auth[7:].strip())
        except Exception:
            return ResponseBuilder.no_permission('invalid_monitor_token')
        g.current_monitor = monitor
        g.monitor_claims = claims
        return func(*args, **kwargs)
    return wrapper


def roles_required(*role_names: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = g.get('current_user')
            if user is None:
                return ResponseBuilder.no_permission('authentication_required')
            role = user.role.name if user.role else None
            if role not in role_names:
                _audit_denied(user, 'role:%s' % ','.join(role_names))
                return ResponseBuilder.forbidden('permission_denied')
            return func(*args, **kwargs)
        return wrapper
    return decorator


def camera_scope_guard(camera_uuid: str, action: str = 'view'):
    """Per-camera scope check (PLAN §4.9). Returns an error Response or None."""
    user = g.get('current_user')
    if user is None:
        return ResponseBuilder.no_permission('authentication_required')
    if not PermissionService.has_camera_scope(user, camera_uuid, action):
        _audit_denied(user, 'camera_scope:%s:%s' % (camera_uuid, action))
        return ResponseBuilder.forbidden('camera_scope_denied')
    return None


def ptz_guard(camera_uuid: str):
    """PTZ = ptz:control AND camera_scope[uuid] ⊇ ptz. Returns an error Response or None."""
    user = g.get('current_user')
    if user is None:
        return ResponseBuilder.no_permission('authentication_required')
    if not PermissionService.can_ptz(user, camera_uuid):
        _audit_denied(user, 'ptz:%s' % camera_uuid)
        return ResponseBuilder.forbidden('ptz_denied')
    return None


def _audit_denied(user, target: str):
    try:
        AuditLog.record(
            action=ACTION_PERMISSION_DENIED, target=target, user_id=user.id,
            method=request.method, path=request.path, ip=request.remote_addr,
            user_agent=request.user_agent.string,
        )
    except Exception:
        from server.model import db
        db.session.rollback()
