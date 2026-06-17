from tests.conftest import login


def _create_viewer(client, headers, **override):
    payload = {
        'login_id': 'viewer', 'password': 'viewer1234!', 'name': '뷰어',
        'role': 'user', 'permissions': {'live': ['read']},
    }
    payload.update(override)
    return client.post('/api/v1/admin/users', headers=headers, json=payload)


def test_user_crud_and_pagination(client):
    headers = login(client)

    created = _create_viewer(client, headers)
    assert created.status_code == 200
    uuid = created.json['data']['uuid']
    assert 'password' not in created.json['data']  # never leak

    listed = client.get('/api/v1/admin/users?page=1&items_per_page=20', headers=headers)
    assert listed.status_code == 200
    body = listed.json['data']
    assert set(body) == {'items', 'pagination'}
    assert body['pagination']['total'] >= 2

    assert client.get(f'/api/v1/admin/users/{uuid}', headers=headers).status_code == 200

    updated = client.post(f'/api/v1/admin/users/{uuid}', headers=headers, json={'name': '뷰어2'})
    assert updated.status_code == 200 and updated.json['data']['name'] == '뷰어2'

    assert client.delete(f'/api/v1/admin/users/{uuid}', headers=headers).status_code == 200
    assert client.get(f'/api/v1/admin/users/{uuid}', headers=headers).status_code == 404  # soft-deleted


def test_duplicate_login_id_conflicts(client):
    headers = login(client)
    assert _create_viewer(client, headers).status_code == 200
    assert _create_viewer(client, headers).status_code == 409


def test_weak_password_rejected(client):
    headers = login(client)
    assert _create_viewer(client, headers, password='short').status_code == 400


def test_rbac_permission_enforced(client):
    headers = login(client)
    _create_viewer(client, headers)
    viewer = login(client, 'viewer', 'viewer1234!')
    # viewer lacks users:read
    assert client.get('/api/v1/admin/users', headers=viewer).status_code == 403
    # but can read its own profile
    assert client.get('/api/v1/auth/me', headers=viewer).status_code == 200


def test_reset_password_invalidates_existing_tokens(client):
    headers = login(client)
    uuid = _create_viewer(client, headers).json['data']['uuid']
    viewer = login(client, 'viewer', 'viewer1234!')
    assert client.get('/api/v1/auth/me', headers=viewer).status_code == 200

    reset = client.post(f'/api/v1/admin/users/{uuid}/reset_password', headers=headers,
                        json={'password': 'brandnew123'})
    assert reset.status_code == 200
    # token_version bumped -> old access invalid
    assert client.get('/api/v1/auth/me', headers=viewer).status_code == 401


def test_unlock_account(client):
    headers = login(client)
    uuid = _create_viewer(client, headers).json['data']['uuid']
    for _ in range(5):
        client.post('/api/v1/auth/login', json={'login_id': 'viewer', 'password': 'bad'})
    assert client.post('/api/v1/auth/login', json={'login_id': 'viewer', 'password': 'viewer1234!'}).status_code == 429
    assert client.post(f'/api/v1/admin/users/{uuid}/unlock', headers=headers).status_code == 200
    assert client.post('/api/v1/auth/login', json={'login_id': 'viewer', 'password': 'viewer1234!'}).status_code == 200


def test_roles_and_permission_catalog(client):
    headers = login(client)
    roles = client.get('/api/v1/admin/roles', headers=headers)
    assert roles.status_code == 200
    assert {r['name'] for r in roles.json['data']} >= {'admin', 'user'}

    perms = client.get('/api/v1/admin/permissions', headers=headers)
    assert perms.status_code == 200
    assert len(perms.json['data']) >= 60  # full P0–P5 catalog seeded


def test_role_permission_validation(client):
    headers = login(client)
    # unknown permission resource is rejected by the catalog validator
    r = client.post('/api/v1/admin/roles', headers=headers,
                    json={'name': 'ops', 'display_name': 'Ops', 'permissions': {'bogus': ['read']}})
    assert r.status_code == 400


def test_audit_logs_admin_only(client):
    headers = login(client)
    assert client.get('/api/v1/admin/audit_logs', headers=headers).status_code == 200
    _create_viewer(client, headers)
    viewer = login(client, 'viewer', 'viewer1234!')
    assert client.get('/api/v1/admin/audit_logs', headers=viewer).status_code == 403


def test_cannot_delete_last_admin(client):
    headers = login(client)
    me = client.get('/api/v1/auth/me', headers=headers).json['data']['user']
    assert client.delete(f"/api/v1/admin/users/{me['uuid']}", headers=headers).status_code == 400
