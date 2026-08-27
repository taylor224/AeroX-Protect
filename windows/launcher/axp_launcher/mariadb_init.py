"""MariaDB first-run initialization + app database bootstrap (idempotent)."""
import logging
import subprocess

from . import env

logger = logging.getLogger(__name__)

DATADIR = env.DATA / 'mariadb'


def needs_init() -> bool:
    return not (DATADIR / 'mysql').exists()


def initialize(cfg: dict[str, str]):
    """Create the datadir with the root password from axp.env (install-time secret)."""
    DATADIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(env.MARIADB_INSTALL_DB),
        '--datadir=%s' % DATADIR,
        '--password=%s' % cfg.get('DB_ROOT_PW', ''),
        '--default-user',   # run mariadbd as the current (service) account
        '--skip-networking=0',
    ]
    logger.info('initializing MariaDB datadir at %s', DATADIR)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError('mariadb-install-db failed: %s' % (r.stderr or r.stdout))


def ensure_database(cfg: dict[str, str]):
    """CREATE DATABASE/USER IF NOT EXISTS + GRANT — safe to run every boot."""
    db = cfg.get('DATABASE_DB', 'axp')
    user = cfg.get('DATABASE_ID', 'axp')
    pw = (cfg.get('DATABASE_PW', '') or '').replace("'", "''")
    sql = (
        "CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        "CREATE USER IF NOT EXISTS '{user}'@'localhost' IDENTIFIED BY '{pw}';"
        "CREATE USER IF NOT EXISTS '{user}'@'127.0.0.1' IDENTIFIED BY '{pw}';"
        "ALTER USER '{user}'@'localhost' IDENTIFIED BY '{pw}';"
        "ALTER USER '{user}'@'127.0.0.1' IDENTIFIED BY '{pw}';"
        "GRANT ALL PRIVILEGES ON `{db}`.* TO '{user}'@'localhost';"
        "GRANT ALL PRIVILEGES ON `{db}`.* TO '{user}'@'127.0.0.1';"
        "FLUSH PRIVILEGES;"
    ).format(db=db, user=user, pw=pw)
    r = subprocess.run(
        [str(env.MARIADB_CLI), '-h', '127.0.0.1', '-P', str(env.DB_PORT),
         '-uroot', '-p%s' % cfg.get('DB_ROOT_PW', ''), '-e', sql],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('database bootstrap failed: %s' % (r.stderr or r.stdout))


def dump(cfg: dict[str, str], out_path) -> bool:
    """mariadb-dump of the app schema (pre-update backup). Returns success."""
    try:
        with open(out_path, 'wb') as f:
            r = subprocess.run(
                [str(env.MARIADB_DUMP), '-h', '127.0.0.1', '-P', str(env.DB_PORT),
                 '-uroot', '-p%s' % cfg.get('DB_ROOT_PW', ''),
                 '--single-transaction', '--routines', '--events',
                 '--databases', cfg.get('DATABASE_DB', 'axp')],
                stdout=f, stderr=subprocess.PIPE, timeout=3600)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restore(cfg: dict[str, str], dump_path) -> bool:
    """Restore a pre-update dump (rollback path)."""
    try:
        with open(dump_path, 'rb') as f:
            r = subprocess.run(
                [str(env.MARIADB_CLI), '-h', '127.0.0.1', '-P', str(env.DB_PORT),
                 '-uroot', '-p%s' % cfg.get('DB_ROOT_PW', '')],
                stdin=f, capture_output=True, timeout=3600)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def shutdown(cfg: dict[str, str]) -> bool:
    try:
        r = subprocess.run(
            [str(env.MARIADB_ADMIN), '-h', '127.0.0.1', '-P', str(env.DB_PORT),
             '-uroot', '-p%s' % cfg.get('DB_ROOT_PW', ''), 'shutdown'],
            capture_output=True, timeout=90)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
