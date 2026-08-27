"""Install-tree paths + config\\axp.env parsing + per-child environment assembly."""
import os
from pathlib import Path

AXP_HOME = Path(os.environ.get('AXP_HOME', r'C:\AeroXProtect'))

RUNTIME = AXP_HOME / 'runtime'
VERSIONS = AXP_HOME / 'versions'
CURRENT = AXP_HOME / 'current'          # directory junction -> versions\v<X.Y.Z>
CONFIG = AXP_HOME / 'config'
DATA = AXP_HOME / 'data'
LOGS = DATA / 'logs'
STAGING = DATA / 'staging'
BACKUPS = DATA / 'backups'
STORAGE = AXP_HOME / 'storage'

ENV_FILE = CONFIG / 'axp.env'
INSTALLED_FILE = CONFIG / 'installed.json'

PYTHON = RUNTIME / 'python' / 'python.exe'
FFMPEG = RUNTIME / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
FFPROBE = RUNTIME / 'ffmpeg' / 'bin' / 'ffprobe.exe'
GO2RTC = RUNTIME / 'go2rtc' / 'go2rtc.exe'
CADDY = RUNTIME / 'caddy' / 'caddy.exe'
REDIS_SERVER = RUNTIME / 'redis' / 'redis-server.exe'
REDIS_CLI = RUNTIME / 'redis' / 'redis-cli.exe'
MARIADBD = RUNTIME / 'mariadb' / 'bin' / 'mariadbd.exe'
MARIADB_CLI = RUNTIME / 'mariadb' / 'bin' / 'mariadb.exe'
MARIADB_DUMP = RUNTIME / 'mariadb' / 'bin' / 'mariadb-dump.exe'
MARIADB_ADMIN = RUNTIME / 'mariadb' / 'bin' / 'mariadb-admin.exe'
MARIADB_INSTALL_DB = RUNTIME / 'mariadb' / 'bin' / 'mariadb-install-db.exe'
WATERMARK_FONT = RUNTIME / 'fonts' / 'DejaVuSans.ttf'

# Loopback, non-default ports so an existing MySQL/Redis on the host can't collide.
DB_PORT = 3307
REDIS_PORT = 6380
BACKEND_PORT = 10000
GO2RTC_API_PORT = 1984
GO2RTC_RTSP_PORT = 8554
ENCODER_PORT = 8098
DETECTOR_PORT = 8099
CONTROL_PORT = 10099


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse the dotenv-style config file written by the installer (KEY=VALUE,
    '#' comments). ACL'd to SYSTEM/Administrators — it holds the secrets."""
    cfg: dict[str, str] = {}
    if not path.exists():
        return cfg
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        cfg[key.strip()] = value.strip().strip('"')
    return cfg


def current_version() -> str:
    """Version of the tree the `current` junction points at ('0.0.0' if missing)."""
    try:
        return (CURRENT / 'VERSION').read_text(encoding='utf-8').strip()
    except OSError:
        return '0.0.0'


def version_dir(version: str) -> Path:
    return VERSIONS / ('v%s' % version.lstrip('v'))


def app_env(cfg: dict[str, str], version_root: Path | None = None,
            extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for an application child process (backend / workers / recorder).

    TZ=UTC is load-bearing: ffmpeg -strftime segment names are parsed as naive UTC
    by the segment indexer (see worker/recorder/__main__.py tripwire).
    """
    root = version_root or CURRENT
    env = dict(os.environ)
    env.update({
        'PROJECT_ENV': 'production',
        'TZ': 'UTC',
        'PYTHONUNBUFFERED': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': '%s;%s' % (root / 'site-packages', root / 'app'),
        'AXP_HOME': str(AXP_HOME),
        'AXP_VERSION': (root / 'VERSION').read_text(encoding='utf-8').strip()
                        if (root / 'VERSION').exists() else current_version(),
        'DATABASE_URL': '127.0.0.1:%d' % DB_PORT,
        'DATABASE_ID': cfg.get('DATABASE_ID', 'axp'),
        'DATABASE_PW': cfg.get('DATABASE_PW', ''),
        'DATABASE_DB': cfg.get('DATABASE_DB', 'axp'),
        'REDIS_URL': '127.0.0.1:%d' % REDIS_PORT,
        'SECRET_KEY': cfg.get('SECRET_KEY', ''),
        'JWT_SECRET': cfg.get('JWT_SECRET', ''),
        'CREDENTIAL_ENC_KEY': cfg.get('CREDENTIAL_ENC_KEY', ''),
        'GO2RTC_URL': 'http://127.0.0.1:%d' % GO2RTC_API_PORT,
        'GO2RTC_RTSP': 'rtsp://127.0.0.1:%d' % GO2RTC_RTSP_PORT,
        'AXP_DISK_ROOT': cfg.get('AXP_DISK_ROOT', str(STORAGE)),
        'AXP_THUMB_DIR': cfg.get('AXP_THUMB_DIR', str(DATA / 'media' / 'thumbnails')),
        'FFMPEG_BIN': str(FFMPEG),
        'FFPROBE_BIN': str(FFPROBE),
        'AXP_WATERMARK_FONT': str(WATERMARK_FONT),
        'AXP_LAUNCHER_URL': 'http://127.0.0.1:%d' % CONTROL_PORT,
        'AXP_LAUNCHER_TOKEN': cfg.get('AXP_LAUNCHER_TOKEN', ''),
        'AXP_DB_INIT': 'false',
    })
    if extra:
        env.update(extra)
    return env
