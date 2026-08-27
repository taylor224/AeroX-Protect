"""Versioned SQL migration runner — the single schema path for Docker AND native installs.

History: migrations/*.sql used to run only via MySQL's docker-entrypoint-initdb.d
(first boot of an empty volume), and `migrate` was just `db.create_all()`. That
left no way to apply an ALTER to an existing deployment automatically — which the
native auto-updater needs. This runner adds a `schema_migrations` version table:

- fresh DB (no `roles` table): models are the schema SSOT → create_all() + mark
  every migration file as baseline-applied (never replay 0000-0020; 0000 even
  does CREATE DATABASE/DROPs).
- existing DB with an empty `schema_migrations` (= every pre-runner deployment,
  Docker volumes included): baseline-mark all files currently on disk, apply nothing.
- otherwise: apply pending files in numeric order, recording version + sha256 +
  duration. MySQL/MariaDB DDL is non-transactional — a failure stops the run and
  raises MigrationError; the native updater then restores its pre-update dump.

Files may contain multiple statements; `USE`/`CREATE DATABASE` lines are stripped
(the connection already targets the configurable DATABASE_DB schema).
"""
import hashlib
import logging
import os
import re
import time

import config

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'migrations')

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS `schema_migrations` (
  `version`     VARCHAR(64)  NOT NULL,
  `filename`    VARCHAR(255) NOT NULL,
  `checksum`    CHAR(64)     NOT NULL,
  `note`        VARCHAR(255) NULL,
  `applied_at`  DATETIME(3)  NOT NULL,
  `duration_ms` INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DB_STMT_RE = re.compile(r'^\s*(USE|CREATE\s+DATABASE)\b[^;]*;\s*$',
                         re.IGNORECASE | re.MULTILINE)


class MigrationError(RuntimeError):
    def __init__(self, version: str, cause: Exception):
        super().__init__('migration %s failed: %s' % (version, cause))
        self.version = version


def _connect():
    import pymysql
    from pymysql.constants import CLIENT
    host, _, port = config.DATABASE_URL.partition(':')
    return pymysql.connect(
        host=host, port=int(port or 3306),
        user=config.DATABASE_ID, password=config.DATABASE_PW,
        database=config.DATABASE_DB, charset='utf8mb4', autocommit=True,
        client_flag=CLIENT.MULTI_STATEMENTS)


def discover(migrations_dir: str | None = None) -> list[tuple[str, str, str]]:
    """[(version, filename, abs_path)] sorted by numeric prefix."""
    d = migrations_dir or MIGRATIONS_DIR
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.endswith('.sql'):
            out.append((name.split('_', 1)[0], name, os.path.join(d, name)))
    out.sort(key=lambda t: t[0])
    return out


def strip_db_statements(sql: str) -> str:
    """Drop USE / CREATE DATABASE lines — the connection already targets the schema."""
    return _DB_STMT_RE.sub('', sql)


def _table_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s',
            (config.DATABASE_DB, name))
        return cur.fetchone() is not None


def _applied(conn) -> dict[str, str]:
    """{version: checksum} of applied migrations."""
    with conn.cursor() as cur:
        cur.execute('SELECT version, checksum FROM `schema_migrations`')
        return {row[0]: row[1] for row in cur.fetchall()}


def _record(conn, version: str, filename: str, checksum: str, note: str | None, duration_ms: int):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO `schema_migrations` (version, filename, checksum, note, applied_at, duration_ms) '
            'VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(3), %s)',
            (version, filename, checksum, note, duration_ms))


def _checksum(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _run_file(conn, path: str):
    with open(path, 'r', encoding='utf-8') as f:
        sql = strip_db_statements(f.read()).strip()
    if not sql:
        return
    with conn.cursor() as cur:
        cur.execute(sql)
        while cur.nextset() is not None:   # drain multi-statement results
            pass


def status() -> dict:
    """{'applied': [version…], 'pending': [version…]} — for the updater precheck / UI."""
    conn = _connect()
    try:
        if not _table_exists(conn, 'schema_migrations'):
            return {'applied': [], 'pending': [v for v, _, _ in discover()]}
        applied = _applied(conn)
        return {'applied': sorted(applied),
                'pending': [v for v, _, _ in discover() if v not in applied]}
    finally:
        conn.close()


def upgrade(create_all_fn=None) -> dict:
    """Bring the schema up to date. Returns {'mode', 'baselined', 'applied'}.

    create_all_fn: builds the full schema from the SQLAlchemy models (fresh path);
    passed in by server.command to avoid importing the ORM here.
    """
    conn = _connect()
    try:
        files = discover()
        with conn.cursor() as cur:
            cur.execute(_TABLE_DDL)

        if not _table_exists(conn, 'roles'):
            # Fresh install — models are the SSOT; migration files describe history
            # already embodied in the models, so mark them applied without running.
            if create_all_fn is not None:
                create_all_fn()
            for version, filename, path in files:
                _record(conn, version, filename, _checksum(path), 'baseline:create_all', 0)
            logger.info('db_migrate: fresh schema created; baselined %d migrations', len(files))
            return {'mode': 'fresh', 'baselined': [v for v, _, _ in files], 'applied': []}

        applied = _applied(conn)
        if not applied:
            # Pre-runner deployment (Docker volume initialized via initdb.d, or an
            # older native create_all install) — trust the live schema as current.
            for version, filename, path in files:
                _record(conn, version, filename, _checksum(path), 'baseline:existing', 0)
            logger.info('db_migrate: baselined existing schema at %s',
                        files[-1][0] if files else '-')
            return {'mode': 'baseline', 'baselined': [v for v, _, _ in files], 'applied': []}

        ran = []
        for version, filename, path in files:
            checksum = _checksum(path)
            if version in applied:
                if applied[version] != checksum:
                    logger.warning('db_migrate: checksum drift on applied %s (file edited?)', filename)
                continue
            t0 = time.monotonic()
            try:
                _run_file(conn, path)
            except Exception as e:
                logger.exception('db_migrate: %s failed', filename)
                raise MigrationError(version, e) from e
            _record(conn, version, filename, checksum, None,
                    int((time.monotonic() - t0) * 1000))
            ran.append(version)
            logger.info('db_migrate: applied %s', filename)
        return {'mode': 'incremental', 'baselined': [], 'applied': ran}
    finally:
        conn.close()
