"""JWT token service (PLAN §5.2, §12.1).

access:  {sub, uuid, role, tv, aud, typ='access', iss, iat, exp(+15m), jti}
refresh: {sub,            aud, typ='refresh', iss, iat, exp(+14d), jti, fid}

- `aud` ∈ {web, monitor, node, api, share}; P0 issues `web`. Verifier is aud-agnostic
  (scoped tokens reuse it in later phases).
- Revocation: Redis denylist key `axp:denylist:<jti>` (TTL = token remainder), plus
  `tv` (token_version) match against the user row for global invalidation.
- Refresh rotation persists a `refresh_tokens` family row; replay of an already-rotated
  refresh is treated as theft -> whole family revoked (TokenReuseException).
"""
import uuid
from datetime import timedelta

import jwt
import redis

import config
from server.exception import AuthenticationException, TokenReuseException
from server.model import UTC, utcnow
from server.model.refresh_token import RefreshToken
from server.model.user import User

DENYLIST_PREFIX = '%s:denylist:' % config.REDIS_KEY_PREFIX

_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(config.REDIS_URI, decode_responses=True)
    return _redis_client


def set_redis(client):
    """Test hook — inject a fakeredis client."""
    global _redis_client
    global _redis_binary_client
    _redis_client = client
    _redis_binary_client = client


_redis_binary_client = None


def get_redis_binary():
    """Redis client that returns raw bytes (decode_responses=False) — for binary blobs like
    cached JPEG thumbnails that the text client can't decode."""
    global _redis_binary_client
    if _redis_binary_client is None:
        _redis_binary_client = redis.from_url(config.REDIS_URI, decode_responses=False)
    return _redis_binary_client


def _epoch(dt) -> int:
    # Our datetimes are naive UTC; naive .timestamp() would assume LOCAL tz.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


class TokenService:
    # ── issue ─────────────────────────────────────────────────────────────────
    @classmethod
    def issue_pair(cls, user: User, aud: str = 'web', user_agent: str | None = None,
                   ip: str | None = None, family_id: str | None = None) -> dict:
        now = utcnow()
        access_jti = uuid.uuid4().hex
        refresh_jti = uuid.uuid4().hex
        fid = family_id or uuid.uuid4().hex
        access_exp = now + timedelta(seconds=config.JWT_ACCESS_TTL)
        refresh_exp = now + timedelta(seconds=config.JWT_REFRESH_TTL)
        role_name = user.role.name if user.role else None

        access_claims = {
            'sub': str(user.id), 'uuid': user.uuid, 'role': role_name,
            'tv': user.token_version or 0, 'aud': aud, 'typ': 'access',
            'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(access_exp),
            'jti': access_jti,
        }
        refresh_claims = {
            'sub': str(user.id), 'aud': aud, 'typ': 'refresh',
            'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(refresh_exp),
            'jti': refresh_jti, 'fid': fid,
        }

        RefreshToken.create(
            user_id=user.id, jti=refresh_jti, family_id=fid,
            issued_at=now, expires_at=refresh_exp, user_agent=user_agent, ip=ip)

        return {
            'access_token': cls._encode(access_claims),
            'refresh_token': cls._encode(refresh_claims),
            'access_jti': access_jti,
            'refresh_jti': refresh_jti,
            'family_id': fid,
            'expires_in': config.JWT_ACCESS_TTL,
            'refresh_expires_at': refresh_exp,
        }

    # ── scoped AI node tokens (P4 §7.2) ────────────────────────────────────────
    @classmethod
    def issue_node_token(cls, node_uuid: str, ttl_days: int | None = None) -> dict:
        """Long-lived scoped token for a joined node (aud=node, sub=node.uuid, jti)."""
        now = utcnow()
        days = config.NODE_TOKEN_TTL_DAYS if ttl_days is None else ttl_days
        exp = now + timedelta(days=days)
        jti = uuid.uuid4().hex
        claims = {
            'sub': node_uuid, 'aud': 'node', 'typ': 'node',
            'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(exp), 'jti': jti,
        }
        return {'token': cls._encode(claims), 'jti': jti, 'expires_at': exp}

    @classmethod
    def issue_join_token(cls, node_id: int, ttl_minutes: int | None = None) -> str:
        """One-time bootstrap token (aud=node-join). jti is tracked in Redis and burned on use."""
        now = utcnow()
        minutes = config.NODE_JOIN_TTL_MINUTES if ttl_minutes is None else ttl_minutes
        exp = now + timedelta(minutes=minutes)
        jti = uuid.uuid4().hex
        claims = {
            'sub': str(node_id), 'aud': 'node-join', 'typ': 'node_join',
            'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(exp), 'jti': jti,
        }
        get_redis().setex('%s:nodejoin:%s' % (config.REDIS_KEY_PREFIX, jti),
                          max(1, int(minutes * 60)), str(node_id))
        return cls._encode(claims)

    @classmethod
    def verify_node_token(cls, token: str) -> dict:
        """Verify a node token (aud=node, jti not denylisted). Raises on failure."""
        claims = cls._decode(token, 'node')
        if claims.get('aud') != 'node':
            raise AuthenticationException('wrong_audience')
        if cls.is_denylisted(claims['jti']):
            raise AuthenticationException('revoked')
        return claims

    @classmethod
    def consume_join_token(cls, token: str) -> int:
        """Verify + burn a one-time join token; returns the pre-registered node_id."""
        claims = cls._decode(token, 'node_join')
        if claims.get('aud') != 'node-join':
            raise AuthenticationException('wrong_audience')
        key = '%s:nodejoin:%s' % (config.REDIS_KEY_PREFIX, claims['jti'])
        node_id = get_redis().get(key)
        if node_id is None:
            raise AuthenticationException('join_token_used_or_expired')
        get_redis().delete(key)   # one-time
        return int(claims['sub'])

    # ── monitor scoped tokens (P5 §7.1) ────────────────────────────────────────
    @classmethod
    def issue_monitor_pair(cls, monitor, dashboard_uuid: str, family_id: str | None = None) -> dict:
        """audience=monitor access+refresh (viewer-only; sub=monitor.uuid, mv, scope)."""
        now = utcnow()
        access_jti, refresh_jti = uuid.uuid4().hex, uuid.uuid4().hex
        fid = family_id or uuid.uuid4().hex
        mv = monitor.token_version or 0
        scope = {'monitor_id': monitor.uuid, 'dashboards': [dashboard_uuid], 'actions': ['read']}
        access_exp = now + timedelta(seconds=config.JWT_ACCESS_TTL)
        refresh_exp = now + timedelta(seconds=config.MONITOR_REFRESH_TTL_S)
        access = {'sub': monitor.uuid, 'aud': 'monitor', 'typ': 'access', 'mv': mv, 'scope': scope,
                  'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(access_exp), 'jti': access_jti}
        refresh = {'sub': monitor.uuid, 'aud': 'monitor', 'typ': 'refresh', 'mv': mv, 'fid': fid,
                   'iss': config.JWT_ISSUER, 'iat': _epoch(now), 'exp': _epoch(refresh_exp), 'jti': refresh_jti}
        return {'access_token': cls._encode(access), 'refresh_token': cls._encode(refresh),
                'token_type': 'Bearer', 'expires_in': config.JWT_ACCESS_TTL, 'family_id': fid, 'scope': scope}

    @classmethod
    def verify_monitor_access(cls, token: str):
        """Returns (monitor, claims). Raises on aud/mv/denylist/disabled failures."""
        claims = cls._decode(token, 'access')
        if claims.get('aud') != 'monitor':
            raise AuthenticationException('wrong_audience')
        if cls.is_denylisted(claims['jti']):
            raise AuthenticationException('revoked')
        mon = cls._live_monitor(claims)
        return mon, claims

    @classmethod
    def rotate_monitor_refresh(cls, token: str) -> dict:
        claims = cls._decode(token, 'refresh')
        if claims.get('aud') != 'monitor':
            raise AuthenticationException('wrong_audience')
        if cls.is_denylisted(claims['jti']):
            raise AuthenticationException('revoked')
        mon = cls._live_monitor(claims)
        from server.model.dashboard import Dashboard
        dash = Dashboard.get_by_id(mon.dashboard_id)
        cls.revoke(claims['jti'], cls._remaining_ttl(claims))   # rotate: old refresh unusable
        pair = cls.issue_monitor_pair(mon, dash.uuid if dash else '', family_id=claims.get('fid'))
        pair['monitor'] = mon
        return pair

    @staticmethod
    def _live_monitor(claims):
        from server.model.monitor import Monitor
        mon = Monitor.get_by_uuid(claims.get('sub', ''))
        if not mon or not mon.enabled or mon.deleted_at is not None:
            raise AuthenticationException('monitor_invalid')
        if (mon.token_version or 0) != claims.get('mv'):
            raise AuthenticationException('stale_monitor_token')
        return mon

    # ── decode / verify ────────────────────────────────────────────────────────
    @staticmethod
    def _encode(claims: dict) -> str:
        return jwt.encode(claims, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)

    @staticmethod
    def _decode(token: str, expected_typ: str) -> dict:
        try:
            claims = jwt.decode(
                token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM],
                issuer=config.JWT_ISSUER,
                options={'verify_aud': False, 'require': ['exp', 'iat', 'jti', 'sub']},
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationException('token_expired')
        except jwt.InvalidTokenError:
            raise AuthenticationException('invalid_token')

        if claims.get('typ') != expected_typ:
            raise AuthenticationException('wrong_token_type')
        return claims

    @classmethod
    def verify_access(cls, token: str) -> tuple[User, dict]:
        """Full access-token verification. Raises AuthenticationException on any failure."""
        claims = cls._decode(token, 'access')

        if cls.is_denylisted(claims['jti']):
            raise AuthenticationException('revoked')

        try:
            user = User.get_by_id(int(claims['sub']))
        except Exception:
            raise AuthenticationException('unknown_user')

        if not user.is_active or user.deleted_at is not None:
            raise AuthenticationException('inactive_user')
        if (user.token_version or 0) != claims.get('tv'):
            raise AuthenticationException('stale_token')

        return user, claims

    @classmethod
    def resolve_access_token(cls, token: str) -> tuple[User | None, dict | None]:
        """Non-raising variant for before_request. Returns (None, None) on any failure."""
        try:
            return cls.verify_access(token)
        except Exception:
            return None, None

    # ── refresh rotation + reuse detection ─────────────────────────────────────
    @classmethod
    def rotate_refresh(cls, token: str, user_agent: str | None = None,
                       ip: str | None = None) -> dict:
        claims = cls._decode(token, 'refresh')
        jti = claims['jti']
        fid = claims.get('fid')

        row = RefreshToken.get_by_jti(jti)
        if row is None:
            raise AuthenticationException('unknown_refresh')

        # Replay of an already-rotated/revoked refresh => theft. Burn the family.
        if row.rotated_to_jti is not None or row.revoked_at is not None:
            RefreshToken.revoke_family(row.family_id)
            cls.revoke(jti, cls._remaining_ttl(claims))
            raise TokenReuseException('refresh_reuse_detected')

        if row.expires_at <= utcnow():
            raise AuthenticationException('refresh_expired')

        try:
            user = User.get_by_id(int(claims['sub']))
        except Exception:
            raise AuthenticationException('unknown_user')
        if not user.is_active or user.deleted_at is not None:
            raise AuthenticationException('inactive_user')

        pair = cls.issue_pair(user, aud=claims.get('aud', 'web'),
                              user_agent=user_agent, ip=ip, family_id=fid)
        row.mark_rotated(pair['refresh_jti'])
        cls.revoke(jti, cls._remaining_ttl(claims))  # old refresh can't be reused
        pair['user'] = user
        return pair

    # ── revocation ─────────────────────────────────────────────────────────────
    @classmethod
    def revoke(cls, jti: str, ttl_seconds: int):
        if ttl_seconds <= 0:
            ttl_seconds = 1
        get_redis().setex(DENYLIST_PREFIX + jti, ttl_seconds, '1')

    @staticmethod
    def is_denylisted(jti: str) -> bool:
        return get_redis().exists(DENYLIST_PREFIX + jti) == 1

    @classmethod
    def revoke_pair(cls, access_claims: dict | None, refresh_jti: str | None = None):
        """Logout: denylist current access + (optionally) the refresh jti + its family."""
        if access_claims and access_claims.get('jti'):
            cls.revoke(access_claims['jti'], cls._remaining_ttl(access_claims))
        if refresh_jti:
            row = RefreshToken.get_by_jti(refresh_jti)
            if row:
                RefreshToken.revoke_family(row.family_id)

    @classmethod
    def revoke_all(cls, user: User):
        """Global invalidation — bump token_version and revoke refresh families."""
        user.bump_token_version()
        RefreshToken.revoke_all_for_user(user.id)

    @staticmethod
    def _remaining_ttl(claims: dict) -> int:
        return max(1, int(claims.get('exp', 0) - _epoch(utcnow())))

    @classmethod
    def decode_unverified_access(cls, token: str) -> dict | None:
        """For logout — read jti/exp even if expired, without enforcing exp."""
        try:
            return jwt.decode(
                token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM],
                options={'verify_aud': False, 'verify_exp': False},
            )
        except jwt.InvalidTokenError:
            return None
