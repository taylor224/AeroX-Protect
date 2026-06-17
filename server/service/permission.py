"""RBAC permission resolution (PLAN §8, §12.2).

Effective permissions = role.permissions (base) deep-merged with user.permissions
(per-user override), unioning action lists per resource. Wildcards: `*` resource
and/or `*` action. The `admin` role carries ``{"*": ["*"]}`` (full access).
"""


class PermissionService:
    @staticmethod
    def effective_permissions(user) -> dict:
        """Merge role + user permission maps into one ``{resource: [actions]}`` dict."""
        merged: dict[str, set] = {}

        for source in (
            (user.role.permissions if user.role else None),
            user.permissions,
        ):
            if not source:
                continue
            for resource, actions in source.items():
                if not isinstance(actions, (list, tuple, set)):
                    continue
                merged.setdefault(resource, set()).update(actions)

        return {resource: sorted(actions) for resource, actions in merged.items()}

    @staticmethod
    def has(user, resource: str, action: str) -> bool:
        if user is None:
            return False
        perms = PermissionService.effective_permissions(user)

        # wildcard resource
        star = perms.get('*')
        if star is not None and ('*' in star or action in star):
            return True

        actions = perms.get(resource)
        if actions is not None and ('*' in actions or action in actions):
            return True

        return False

    @staticmethod
    def is_superuser(user) -> bool:
        if user is None:
            return False
        star = PermissionService.effective_permissions(user).get('*')
        return bool(star and '*' in star)

    @staticmethod
    def _merged_scope(user, key: str) -> dict:
        """Merge a per-scope map (camera_scope/dashboard_scope) from role + user."""
        merged: dict = {}
        for source in (user.role.permissions if user.role else None, user.permissions):
            if isinstance(source, dict) and isinstance(source.get(key), dict):
                merged.update(source[key])  # user overrides role per key
        return merged

    @staticmethod
    def has_camera_scope(user, camera_uuid: str, action: str = 'view') -> bool:
        """PLAN §4.9: per-camera action gate. Default deny for non-superusers."""
        if user is None:
            return False
        if PermissionService.is_superuser(user):
            return True
        scope = PermissionService._merged_scope(user, 'camera_scope')
        allowed = scope.get(camera_uuid)
        if allowed is None:
            allowed = scope.get('*')
        if not allowed:
            return False
        return action in allowed or '*' in allowed

    @staticmethod
    def can_ptz(user, camera_uuid: str) -> bool:
        """PTZ = global ptz:control AND camera_scope[uuid] ⊇ ptz (PLAN §4.9)."""
        if PermissionService.is_superuser(user):
            return True
        return (PermissionService.has(user, 'ptz', 'control')
                and PermissionService.has_camera_scope(user, camera_uuid, 'ptz'))
