"""Credential encryption (Fernet) with key-rotation support (PLAN §11, P1 §4.1).

Camera username/password are stored as Fernet ciphertext (`*_enc` BLOB) plus a
`cred_key_id` recording which key encrypted them, so keys can be rotated without a
flag day. `CREDENTIAL_ENC_KEY` env is one or more comma-separated Fernet keys
(first = primary for encryption; all are tried for decryption).

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import hashlib

from cryptography.fernet import Fernet, InvalidToken

import config


def _key_id(key: str) -> str:
    """Stable 8-hex id for a key (so rotation maps ciphertext -> the right key)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


class CredentialCipher:
    def __init__(self, env_value: str | None):
        self._by_id: dict[str, Fernet] = {}
        self._primary: Fernet | None = None
        self._primary_id: str | None = None
        for raw in (env_value or '').split(','):
            key = raw.strip()
            if not key:
                continue
            fernet = Fernet(key.encode())
            kid = _key_id(key)
            self._by_id[kid] = fernet
            if self._primary is None:
                self._primary, self._primary_id = fernet, kid

    @property
    def configured(self) -> bool:
        return self._primary is not None

    def encrypt(self, plaintext: str) -> tuple[bytes, str]:
        if self._primary is None or self._primary_id is None:
            raise RuntimeError('CREDENTIAL_ENC_KEY not configured')
        return self._primary.encrypt(plaintext.encode()), self._primary_id

    def decrypt(self, token: bytes | str | None, key_id: str | None = None) -> str | None:
        if token is None:
            return None
        if isinstance(token, str):
            token = token.encode()

        fernet = self._by_id.get(key_id) if key_id else None
        if fernet is not None:
            try:
                return fernet.decrypt(token).decode()
            except InvalidToken:
                pass
        # rotation fallback: try every configured key
        for fernet in self._by_id.values():
            try:
                return fernet.decrypt(token).decode()
            except InvalidToken:
                continue
        raise InvalidToken('no configured key could decrypt the credential')


_cipher = CredentialCipher(config.CREDENTIAL_ENC_KEY)


def set_key(env_value: str | None) -> None:
    """Test/rotation hook — rebuild the module cipher from a new env value."""
    global _cipher
    _cipher = CredentialCipher(env_value)


def is_configured() -> bool:
    return _cipher.configured


def encrypt_credential(plaintext: str) -> tuple[bytes, str]:
    return _cipher.encrypt(plaintext)


def decrypt_credential(token: bytes | str | None, key_id: str | None = None) -> str | None:
    return _cipher.decrypt(token, key_id)


def generate_key() -> str:
    return Fernet.generate_key().decode()
