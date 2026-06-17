from tests.conftest import login


def test_healthz(client):
    r = client.get('/api/v1/healthz')
    assert r.status_code == 200
    assert r.json['data']['db'] is True
    assert r.json['data']['redis'] is True


def test_login_and_me(client):
    headers = login(client)
    r = client.get('/api/v1/auth/me', headers=headers)
    assert r.status_code == 200
    assert r.json['data']['permissions'] == {'*': ['*']}
    assert any(m['path'] == '/users' for m in r.json['data']['menus'])


def test_login_sets_refresh_cookie(client):
    r = client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'})
    assert r.status_code == 200
    assert any('axp_refresh' in c for c in r.headers.getlist('Set-Cookie'))


def test_login_bad_password(client):
    r = client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'nope'})
    assert r.status_code == 400
    assert r.json['message'] == 'invalid_credentials'


def test_login_unknown_user(client):
    r = client.post('/api/v1/auth/login', json={'login_id': 'ghost', 'password': 'x'})
    assert r.status_code == 400


def test_me_requires_auth(client):
    assert client.get('/api/v1/auth/me').status_code == 401


def test_brute_force_lockout(client):
    for _ in range(4):
        r = client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'bad'})
        assert r.status_code == 400
    # 5th failure locks the account -> 429
    assert client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'bad'}).status_code == 429
    # correct password while locked -> still 429
    assert client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'}).status_code == 429


def test_refresh_rotation_and_logout(client):
    r = client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'})
    access = r.json['data']['access_token']

    rotated = client.post('/api/v1/auth/refresh')  # cookie sent from jar
    assert rotated.status_code == 200
    assert rotated.json['data']['access_token'] != access

    new_headers = {'Authorization': 'Bearer %s' % rotated.json['data']['access_token']}
    assert client.post('/api/v1/auth/logout', headers=new_headers).status_code == 200
    # access was denylisted at logout
    assert client.get('/api/v1/auth/me', headers=new_headers).status_code == 401


def test_change_password_self(client):
    headers = login(client)
    r = client.post('/api/v1/auth/change_password', headers=headers,
                    json={'previous_password': 'admin1234!', 'password': 'admin5678!'})
    assert r.status_code == 200
    # old password no longer works
    assert client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'admin1234!'}).status_code == 400
    assert client.post('/api/v1/auth/login', json={'login_id': 'admin', 'password': 'admin5678!'}).status_code == 200


def test_language_switch(client):
    headers = login(client)
    r = client.post('/api/v1/auth/language', headers=headers, json={'language': 'en'})
    assert r.status_code == 200
    assert r.json['data']['language'] == 'en'
    assert client.post('/api/v1/auth/language', headers=headers, json={'language': 'xx'}).status_code == 400
