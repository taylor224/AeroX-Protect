"""Twilio SMS config resolution (PLAN P6 N1).

The SMS account can be configured from the admin UI (stored in `settings['twilio']`) or
via `TWILIO_*` env. The DB Setting takes precedence so an operator can set it without a
redeploy. The auth token is the only secret: it is stored Fernet-encrypted (server.util.crypto,
same scheme as camera credentials); the account SID, from-number and API base are not secret
and are stored in clear. `status()` is the UI-safe view (never returns the token).
"""
import logging

import config
from server.util import crypto

logger = logging.getLogger(__name__)

SETTING_KEY = 'twilio'


def _db_row() -> dict:
    try:
        from server.model.setting import Setting
        return Setting.get_value(SETTING_KEY) or {}
    except Exception:                                    # no app/db context → env only
        return {}


def get_config() -> dict:
    """Resolved config for *sending* (DB overrides env, token decrypted)."""
    row = _db_row()
    token = None
    enc = row.get('auth_token_enc')
    if enc:
        try:
            token = crypto.decrypt_credential(enc, row.get('auth_token_key_id'))
        except Exception:
            logger.warning('twilio auth token decrypt failed; falling back to env token')
    return {
        'account_sid': row.get('account_sid') or config.TWILIO_ACCOUNT_SID,
        'auth_token': token or config.TWILIO_AUTH_TOKEN,
        'from_number': row.get('from_number') or config.TWILIO_FROM_NUMBER,
        'api_base': row.get('api_base') or config.TWILIO_API_BASE,
    }


def configured() -> bool:
    c = get_config()
    return bool(c['account_sid'] and c['auth_token'] and c['from_number'])


def set_config(account_sid=None, auth_token=None, from_number=None, api_base=None) -> dict:
    """Persist Twilio config. Only provided (non-None) fields are touched. An empty-string
    `auth_token` clears the stored token. Returns the UI-safe `status()`."""
    from server.model.setting import Setting
    row = dict(_db_row())

    if account_sid is not None:
        row['account_sid'] = (account_sid or '').strip() or None
    if from_number is not None:
        row['from_number'] = (from_number or '').strip() or None
    if api_base is not None:
        row['api_base'] = (api_base or '').strip() or None

    if auth_token is not None:
        token = (auth_token or '').strip()
        if token:
            if not crypto.is_configured():
                raise RuntimeError('CREDENTIAL_ENC_KEY not configured')
            ct, kid = crypto.encrypt_credential(token)
            row['auth_token_enc'] = ct.decode() if isinstance(ct, bytes) else ct
            row['auth_token_key_id'] = kid
        else:                                            # explicit clear
            row.pop('auth_token_enc', None)
            row.pop('auth_token_key_id', None)

    Setting.set_value(SETTING_KEY, row, description='Twilio SMS 설정')
    return status()


def status() -> dict:
    """Non-secret status for the admin UI. The token itself is never returned — only
    whether one is set, and where the config resolves from."""
    row = _db_row()
    sid = row.get('account_sid') or config.TWILIO_ACCOUNT_SID
    from_number = row.get('from_number') or config.TWILIO_FROM_NUMBER
    has_token = bool(row.get('auth_token_enc') or config.TWILIO_AUTH_TOKEN)
    return {
        'account_sid': sid,                              # SID is an account id, not a secret
        'from_number': from_number,
        'has_token': has_token,
        'configured': bool(sid and has_token and from_number),
        'source': 'db' if row else ('env' if config.TWILIO_ACCOUNT_SID else 'none'),
    }
