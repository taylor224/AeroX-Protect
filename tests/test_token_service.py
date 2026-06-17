import pytest

import config
from server.exception import AuthenticationException, TokenReuseException
from server.model.user import User
from server.service.token import TokenService


@pytest.fixture()
def admin(app_db):
    return User.get_by_login_id('admin')


def test_issue_and_verify_roundtrip(admin):
    bundle = TokenService.issue_pair(admin)
    user, claims = TokenService.verify_access(bundle['access_token'])
    assert user.id == admin.id
    assert claims['typ'] == 'access'
    assert claims['aud'] == 'web'
    assert claims['role'] == 'admin'


def test_tampered_signature_rejected(admin):
    bundle = TokenService.issue_pair(admin)
    with pytest.raises(AuthenticationException):
        TokenService.verify_access(bundle['access_token'][:-3] + 'zzz')


def test_expired_access_rejected(admin, monkeypatch):
    monkeypatch.setattr(config, 'JWT_ACCESS_TTL', -10)
    bundle = TokenService.issue_pair(admin)
    with pytest.raises(AuthenticationException):
        TokenService.verify_access(bundle['access_token'])


def test_denylisted_access_rejected(admin):
    bundle = TokenService.issue_pair(admin)
    _, claims = TokenService.verify_access(bundle['access_token'])
    TokenService.revoke(claims['jti'], 100)
    with pytest.raises(AuthenticationException):
        TokenService.verify_access(bundle['access_token'])


def test_token_version_bump_invalidates(admin):
    bundle = TokenService.issue_pair(admin)
    admin.bump_token_version()
    with pytest.raises(AuthenticationException):
        TokenService.verify_access(bundle['access_token'])


def test_rotation_and_reuse_detection(admin):
    bundle = TokenService.issue_pair(admin)
    rotated = TokenService.rotate_refresh(bundle['refresh_token'])
    assert rotated['access_token'] != bundle['access_token']

    # replay of the original (already-rotated) refresh = theft -> family burned
    with pytest.raises(TokenReuseException):
        TokenService.rotate_refresh(bundle['refresh_token'])

    # the just-issued refresh is now revoked too (whole family)
    with pytest.raises((AuthenticationException, TokenReuseException)):
        TokenService.rotate_refresh(rotated['refresh_token'])
