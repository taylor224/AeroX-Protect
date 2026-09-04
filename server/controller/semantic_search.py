"""Semantic search (PLAN P6 A1). Camera-scoped natural-language search over indexed events,
plus an admin/owner reindex trigger. Flag-gated by `semantic_search`.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException
from server.model import UTC
from server.model.audit_log import AuditLog
from server.model.camera import Camera
from server.service import ai_model_setup, feature_flag, semantic_embed, semantic_search
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _allowed_camera_ids(user) -> set[int] | None:
    """Camera ids the user may view (None = all). Default-deny for non-superusers."""
    if PermissionService.is_superuser(user):
        return None
    scope = PermissionService._merged_scope(user, 'camera_scope')
    star = scope.get('*')
    if star and ('view' in star or '*' in star):
        return None
    allowed: set[int] = set()
    for uuid, actions in scope.items():
        if uuid == '*':
            continue
        if 'view' in actions or '*' in actions:
            cam = Camera.get_by_uuid(uuid)
            if cam:
                allowed.add(cam.id)
    return allowed


def _guard_flag():
    if not feature_flag.is_enabled('semantic_search'):
        raise NoPermissionException('feature_disabled')


class SemanticSearchController:
    @classmethod
    def search(cls, user, args) -> dict:
        _guard_flag()
        allowed = _allowed_camera_ids(user)
        requested = [int(c) for c in args.getlist('camera_id') if c.isdigit()] if hasattr(args, 'getlist') else []
        if allowed is not None:
            cam_ids = list(set(requested) & allowed) if requested else list(allowed)
            if not cam_ids:
                return {'backend': semantic_embed.active_backend(), 'count': 0, 'items': []}
        else:
            cam_ids = requested or None
        return semantic_search.search(
            args.get('q', ''), camera_ids=cam_ids,
            start=_parse_ms(args.get('start')), end=_parse_ms(args.get('end')),
            limit=min(50, max(1, safe_int(args.get('limit'), 24))))

    @classmethod
    def reindex(cls, user, data: dict) -> dict:
        _guard_flag()
        allowed = _allowed_camera_ids(user)
        req = data.get('camera_id')
        cam_ids = None
        if req:
            rid = safe_int(req, None)
            if rid is None:
                cam_ids = None
            else:
                if allowed is not None and rid not in allowed:
                    raise NoPermissionException('camera_scope_denied')
                cam_ids = [rid]
        elif allowed is not None:
            cam_ids = list(allowed)
        return semantic_search.index_events(
            camera_ids=cam_ids, start=_parse_ms(data.get('start')), end=_parse_ms(data.get('end')))

    @classmethod
    def model_status(cls, user) -> dict:
        _guard_flag()
        data = ai_model_setup.status()
        data['backend'] = semantic_embed.active_backend()
        return data

    @classmethod
    def model_install(cls, user, data: dict) -> dict:
        """Start the CLIP dep install (view pre-checks supported/409)."""
        _guard_flag()
        variant = data.get('variant') or 'cpu'
        if variant not in ai_model_setup.VARIANTS:
            raise InvalidParameterException('variant must be one of %s' % (ai_model_setup.VARIANTS,))
        started = ai_model_setup.start(variant)
        if started:
            AuditLog.record('clip_install_started', target=variant,
                            user_id=user.id if user else None, detail={'variant': variant})
        return {'started': started}
