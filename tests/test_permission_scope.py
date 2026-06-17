from types import SimpleNamespace

from server.service.permission import PermissionService as P


def _u(role_perms, user_perms):
    return SimpleNamespace(role=SimpleNamespace(permissions=role_perms), permissions=user_perms)


def test_camera_scope_default_deny():
    assert not P.has_camera_scope(_u({'live': ['read']}, {}), 'cam1', 'view')


def test_camera_scope_wildcard():
    u = _u({}, {'camera_scope': {'*': ['view']}})
    assert P.has_camera_scope(u, 'cam1', 'view')
    assert not P.has_camera_scope(u, 'cam1', 'ptz')


def test_camera_scope_specific_overrides_wildcard():
    u = _u({'camera_scope': {'*': ['view']}}, {'camera_scope': {'cam1': ['view', 'ptz']}})
    assert P.has_camera_scope(u, 'cam1', 'ptz')
    assert P.has_camera_scope(u, 'other', 'view')   # falls back to role wildcard
    assert not P.has_camera_scope(u, 'other', 'ptz')


def test_superuser_bypasses_scope():
    u = _u({'*': ['*']}, {})
    assert P.has_camera_scope(u, 'x', 'ptz')
    assert P.can_ptz(u, 'x')


def test_can_ptz_requires_control_and_scope():
    assert P.can_ptz(_u({'ptz': ['control']}, {'camera_scope': {'cam1': ['ptz']}}), 'cam1')
    assert not P.can_ptz(_u({'ptz': ['control']}, {}), 'cam1')               # no scope
    assert not P.can_ptz(_u({}, {'camera_scope': {'cam1': ['ptz']}}), 'cam1')  # no control
