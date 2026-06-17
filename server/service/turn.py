"""Remote-portal ICE/TURN service (PLAN P9). Builds the ICE-server list browsers use for
WebRTC live/playback, including short-lived TURN credentials via the coturn "REST API"
(use-auth-secret) scheme:

    username   = "<expiry_unix_ts>:<user_id>"
    credential = base64( HMAC-SHA1( static_auth_secret, username ) )

coturn validates the HMAC and rejects the username after `expiry`, so we can hand out
time-boxed creds without per-user state. The static secret never leaves the server.
"""
import base64
import hashlib
import hmac
import time

from server.model.turn_config import DEFAULT_STUN, TurnConfig


def ephemeral_credentials(user_id, secret: str, ttl: int) -> tuple[str, str]:
    """(username, credential) for the coturn REST-API auth scheme. Pure given `now` via ttl."""
    expiry = int(time.time()) + max(60, int(ttl or 3600))
    username = '%d:%s' % (expiry, user_id)
    digest = hmac.new(secret.encode('utf-8'), username.encode('utf-8'), hashlib.sha1).digest()
    credential = base64.b64encode(digest).decode('ascii')
    return username, credential


def _turn_urls(cfg: TurnConfig) -> list[str]:
    scheme = 'turns' if cfg.turn_tls else 'turn'
    transport = (cfg.turn_protocol or 'udp').lower()
    return ['%s:%s:%d?transport=%s' % (scheme, cfg.turn_host, cfg.turn_port or 3478, transport)]


def ice_servers(user) -> dict:
    """ICE servers for this user: always STUN; TURN (with ephemeral creds) when configured.
    Returns the Google STUN default if the portal is off, so live never breaks."""
    cfg = TurnConfig.get()
    if cfg is None or not cfg.enabled:
        return {'ice_servers': [{'urls': u} for u in DEFAULT_STUN], 'ttl': 0}

    servers = [{'urls': u} for u in (cfg.stun_urls or DEFAULT_STUN)]
    ttl = int(cfg.ttl_seconds or 3600)
    secret = cfg.get_secret()
    if cfg.turn_host and secret:
        username, credential = ephemeral_credentials(user.id, secret, ttl)
        servers.append({'urls': _turn_urls(cfg), 'username': username, 'credential': credential})
    return {'ice_servers': servers, 'ttl': ttl}
