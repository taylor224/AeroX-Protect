from types import SimpleNamespace

from server.service.permission import PermissionService


def _user(role_perms, user_perms):
    return SimpleNamespace(role=SimpleNamespace(permissions=role_perms), permissions=user_perms)


def test_admin_wildcard_grants_everything():
    u = _user({'*': ['*']}, {})
    assert PermissionService.has(u, 'cameras', 'read')
    assert PermissionService.has(u, 'anything', 'delete')


def test_role_and_user_permissions_merge():
    u = _user({'cameras': ['read']}, {'cameras': ['create'], 'live': ['read']})
    eff = PermissionService.effective_permissions(u)
    assert set(eff['cameras']) == {'read', 'create'}
    assert eff['live'] == ['read']
    assert PermissionService.has(u, 'cameras', 'create')
    assert not PermissionService.has(u, 'cameras', 'delete')


def test_wildcard_action_on_resource():
    u = _user({}, {'users': ['*']})
    assert PermissionService.has(u, 'users', 'delete')
    assert not PermissionService.has(u, 'cameras', 'read')


def test_none_user_denied():
    assert not PermissionService.has(None, 'x', 'y')


def test_user_without_role():
    u = SimpleNamespace(role=None, permissions={'live': ['read']})
    assert PermissionService.has(u, 'live', 'read')
    assert not PermissionService.has(u, 'live', 'create')
