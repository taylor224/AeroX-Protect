import os

# ── General ──────────────────────────────────────────────────────────────────
PROJECT_ENV = os.getenv('PROJECT_ENV')  # 'development' => debug + non-secure cookies
VERSION = os.getenv('AXP_VERSION', '0.0.1')

# ── Database (axp-mysql / schema `axp`) ──────────────────────────────────────
DATABASE_URL = os.getenv('DATABASE_URL', 'axp-mysql')
DATABASE_ID = os.getenv('DATABASE_ID', 'axp')
DATABASE_PW = os.getenv('DATABASE_PW', '')
DATABASE_DB = os.getenv('DATABASE_DB', 'axp')
DATABASE_URI = 'mysql+pymysql://{0}:{1}@{2}/{3}?charset=utf8mb4'.format(
    DATABASE_ID,
    DATABASE_PW,
    DATABASE_URL,
    DATABASE_DB,
)

# ── Redis (jti denylist + Celery broker) ─────────────────────────────────────
REDIS_URI = 'redis://{0}:6379'.format(os.getenv('REDIS_URL', 'axp-redis'))
REDIS_KEY_PREFIX = 'axp'

# ── Flask ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv('SECRET_KEY')

# ── JWT ──────────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv('JWT_SECRET', SECRET_KEY or 'dev-insecure-jwt-secret')
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_TTL = int(os.getenv('JWT_ACCESS_TTL', '900'))          # 15m
JWT_REFRESH_TTL = int(os.getenv('JWT_REFRESH_TTL', '1209600'))    # 14d
JWT_ISSUER = 'axp'
# P4 distributed AI node tokens (aud=node / aud=node-join)
NODE_TOKEN_TTL_DAYS = int(os.getenv('NODE_TOKEN_TTL_DAYS', '30'))
NODE_JOIN_TTL_MINUTES = int(os.getenv('NODE_JOIN_TTL_MINUTES', '30'))
# P5 automation / monitors / notifications / external API
API_TOKEN_PEPPER = os.getenv('API_TOKEN_PEPPER', (SECRET_KEY or '') + ':apitok')
PAIRING_CODE_PEPPER = os.getenv('PAIRING_CODE_PEPPER', (SECRET_KEY or '') + ':pair')
PAIRING_CODE_TTL_S = int(os.getenv('PAIRING_CODE_TTL_S', '60'))
MONITOR_REFRESH_TTL_S = int(os.getenv('MONITOR_REFRESH_TTL_S', str(30 * 24 * 3600)))
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_SUBJECT = os.getenv('VAPID_SUBJECT', 'mailto:admin@aeroxprotect.local')
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_FROM = os.getenv('SMTP_FROM', 'AeroXProtect <noreply@aeroxprotect.local>')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'
# Twilio SMS (P6 N1) — REST API over HTTPS (no SDK; basic auth SID:token).
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_FROM_NUMBER = os.getenv('TWILIO_FROM_NUMBER')
TWILIO_API_BASE = os.getenv('TWILIO_API_BASE', 'https://api.twilio.com')
# Webhook SSRF guard: block private/loopback/metadata IPs (relaxed off-production for local e2e)
WEBHOOK_ALLOW_PRIVATE = os.getenv('WEBHOOK_ALLOW_PRIVATE', '').lower() == 'true' or PROJECT_ENV != 'production'
REFRESH_COOKIE_NAME = 'axp_refresh'
REFRESH_COOKIE_PATH = '/api/v1/auth'

# ── Brute-force lockout ──────────────────────────────────────────────────────
LOGIN_MAX_FAILED = int(os.getenv('LOGIN_MAX_FAILED', '5'))
LOGIN_LOCK_WINDOW_MIN = int(os.getenv('LOGIN_LOCK_WINDOW_MIN', '30'))
LOGIN_LOCK_MINUTES = int(os.getenv('LOGIN_LOCK_MINUTES', '30'))

# ── Snowflake (MUST differ per service: backend=1, worker=2) ─────────────────
SNOWFLAKE_INSTANCE = int(os.getenv('SNOWFLAKE_INSTANCE', '1'))

# ── Camera credential encryption (Fernet) — used P1+ ─────────────────────────
CREDENTIAL_ENC_KEY = os.getenv('CREDENTIAL_ENC_KEY')

# ── go2rtc media hub ─────────────────────────────────────────────────────────
GO2RTC_URL = os.getenv('GO2RTC_URL', 'http://axp-go2rtc:1984')
GO2RTC_RTSP = os.getenv('GO2RTC_RTSP', 'rtsp://axp-go2rtc:8554')

# ── Recording / storage (P2) ─────────────────────────────────────────────────
DISK_ROOT = os.getenv('AXP_DISK_ROOT', '/mnt/axp')       # scanned for pool disks
MIN_WRITE_HEADROOM_BYTES = int(os.getenv('MIN_WRITE_HEADROOM_BYTES', str(2 * 1024 * 1024 * 1024)))  # 2GB
RECORDER_RECONCILE_SECONDS = int(os.getenv('RECORDER_RECONCILE_SECONDS', '10'))
FFMPEG_BIN = os.getenv('FFMPEG_BIN', 'ffmpeg')
FFPROBE_BIN = os.getenv('FFPROBE_BIN', 'ffprobe')
RECONCILE_CHANNEL = '%s:recorder:reconcile' % REDIS_KEY_PREFIX
THUMB_CACHE_PREFIX = '%s:thumb:' % REDIS_KEY_PREFIX
# Persisted last-known camera frame (survives the Redis cache TTL → offline tiles keep
# showing the last frame). Shared `/media` volume is mounted on backend + worker.
THUMB_DIR = os.getenv('AXP_THUMB_DIR', '/media/thumbnails')

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', '*')

# ── Error tracking ───────────────────────────────────────────────────────────
SENTRY_DSN = os.getenv('SENTRY_DSN')

# ── Bootstrap first admin (seed-admin) ───────────────────────────────────────
BOOTSTRAP_ADMIN_ID = os.getenv('BOOTSTRAP_ADMIN_ID', 'admin')
BOOTSTRAP_ADMIN_PW = os.getenv('BOOTSTRAP_ADMIN_PW')
BOOTSTRAP_ADMIN_NAME = os.getenv('BOOTSTRAP_ADMIN_NAME', '관리자')

# ── Fail closed on insecure secret defaults in production ─────────────────────
# JWT_SECRET / SECRET_KEY fall back to public dev constants when unset; with those,
# anyone can forge access tokens and live-WS/share HMAC tickets. Refuse to boot a
# production deployment that hasn't set real secrets.
if PROJECT_ENV == 'production':
    _insecure = []
    if not SECRET_KEY:
        _insecure.append('SECRET_KEY')
    if not os.getenv('JWT_SECRET') and not SECRET_KEY:
        _insecure.append('JWT_SECRET')
    if not CREDENTIAL_ENC_KEY:
        _insecure.append('CREDENTIAL_ENC_KEY')
    if _insecure:
        raise RuntimeError('refusing to start: set %s in production' % ', '.join(_insecure))
