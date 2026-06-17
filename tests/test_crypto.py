import pytest
from cryptography.fernet import InvalidToken

from server.util import crypto


def test_roundtrip():
    token, key_id = crypto.encrypt_credential('s3cret-pass')
    assert isinstance(token, bytes)
    assert token != b's3cret-pass'
    assert crypto.decrypt_credential(token, key_id) == 's3cret-pass'


def test_decrypt_without_key_id_falls_back():
    token, _ = crypto.encrypt_credential('admin')
    assert crypto.decrypt_credential(token, None) == 'admin'


def test_none_passthrough():
    assert crypto.decrypt_credential(None) is None


def test_key_rotation():
    primary = crypto.generate_key()
    old = crypto.generate_key()
    # encrypt under `old` only
    crypto.set_key(old)
    token, old_id = crypto.encrypt_credential('rotated')
    # now primary is new, old kept for decryption
    crypto.set_key('%s,%s' % (primary, old))
    try:
        assert crypto.decrypt_credential(token, old_id) == 'rotated'  # still decryptable
        new_token, new_id = crypto.encrypt_credential('fresh')
        assert new_id != old_id                                       # encrypts under primary
        assert crypto.decrypt_credential(new_token, new_id) == 'fresh'
    finally:
        crypto.set_key('aUHylC1Rzx0OXxLRyPpW8_vT0yy9D8vi7SnK-pnf9fQ=')


def test_wrong_key_rejected():
    other = crypto.generate_key()
    crypto.set_key(other)
    token, kid = crypto.encrypt_credential('x')
    crypto.set_key(crypto.generate_key())  # unrelated key only
    try:
        with pytest.raises(InvalidToken):
            crypto.decrypt_credential(token, kid)
    finally:
        crypto.set_key('aUHylC1Rzx0OXxLRyPpW8_vT0yy9D8vi7SnK-pnf9fQ=')


def test_unconfigured_raises():
    crypto.set_key('')
    try:
        assert crypto.is_configured() is False
        with pytest.raises(RuntimeError):
            crypto.encrypt_credential('x')
    finally:
        crypto.set_key('aUHylC1Rzx0OXxLRyPpW8_vT0yy9D8vi7SnK-pnf9fQ=')
