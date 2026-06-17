"""Pytest fixtures: real Flask app on SQLite + fakeredis, fresh schema per test."""
import os

# Must be set before importing config/server (db_init runs at server import).
os.environ.update(
    PROJECT_ENV='development',           # non-secure cookies so the test client round-trips them
    JWT_SECRET='test-jwt-secret',
    SECRET_KEY='test-secret',
    JWT_ACCESS_TTL='900',
    SNOWFLAKE_INSTANCE='1',
    BOOTSTRAP_ADMIN_ID='admin',
    BOOTSTRAP_ADMIN_PW='admin1234!',
    BOOTSTRAP_ADMIN_NAME='관리자',
    CREDENTIAL_ENC_KEY='aUHylC1Rzx0OXxLRyPpW8_vT0yy9D8vi7SnK-pnf9fQ=',
)

import config  # noqa: E402

config.DATABASE_URI = 'sqlite:////tmp/axp_pytest.db'

import fakeredis  # noqa: E402
import pytest  # noqa: E402

import server.service.token as token_mod  # noqa: E402

_fake_redis = fakeredis.FakeStrictRedis(decode_responses=True)
token_mod.set_redis(_fake_redis)

import server  # noqa: E402  (binds db to sqlite)
from server.command import seed, seed_admin  # noqa: E402
from server.model import BaseDB, db  # noqa: E402


@pytest.fixture()
def app_db():
    """Fresh schema + seed + first admin + clean redis for each test."""
    BaseDB.metadata.drop_all(db.engine)
    BaseDB.metadata.create_all(db.engine)
    seed()
    seed_admin()
    _fake_redis.flushall()
    from server.service import feature_flag  # fresh DB → drop the per-process flag cache
    feature_flag.invalidate()
    db.session.remove()
    yield
    db.session.remove()


@pytest.fixture()
def client(app_db):
    return server.app.test_client()


@pytest.fixture()
def redis_client():
    return _fake_redis


@pytest.fixture()
def mock_go2rtc(monkeypatch):
    """Neutralize go2rtc network calls for camera/dashboard tests."""
    from server.driver import go2rtc as g
    monkeypatch.setattr(g.Go2rtcDriver, 'put_stream', lambda self, name, src: None)
    monkeypatch.setattr(g.Go2rtcDriver, 'delete_stream', lambda self, name: None)
    monkeypatch.setattr(g.Go2rtcDriver, 'stream_status',
                        lambda self, name: {'producers': 0, 'consumers': 0, 'online': False})
    monkeypatch.setattr(g.Go2rtcDriver, 'get_frame', lambda self, name: None)


def create_user(client, headers, login_id, permissions, password='viewer1234!'):
    """Helper: create a non-admin user with specific permissions; return its dict."""
    res = client.post('/api/v1/admin/users', headers=headers, json={
        'login_id': login_id, 'password': password, 'name': login_id.upper(),
        'role': 'user', 'permissions': permissions})
    assert res.status_code == 200, res.json
    return res.json['data']


def login(client, login_id='admin', password='admin1234!'):
    """Return Authorization headers for a logged-in user (admin by default)."""
    res = client.post('/api/v1/auth/login', json={'login_id': login_id, 'password': password})
    assert res.status_code == 200, res.json
    return {'Authorization': 'Bearer %s' % res.json['data']['access_token']}
