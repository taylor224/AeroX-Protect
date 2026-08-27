"""Migration-runner unit tests against a fake pymysql connection (no MySQL needed)."""
import pytest

from server.service import db_migrate


# ── strip_db_statements ───────────────────────────────────────────────────────
def test_strips_use_and_create_database():
    sql = (
        "-- header\n"
        "USE `axp`;\n"
        "CREATE DATABASE IF NOT EXISTS axp;\n"
        "CREATE TABLE t (id INT);\n"
        "use axp;\n"
    )
    out = db_migrate.strip_db_statements(sql)
    assert 'USE' not in out.upper().replace('USER', '')
    assert 'CREATE DATABASE' not in out.upper()
    assert 'CREATE TABLE t (id INT);' in out


def test_strip_keeps_create_user_and_table():
    sql = "CREATE TABLE users (id INT);\nUPDATE segments SET corrupt = 1;\n"
    assert db_migrate.strip_db_statements(sql) == sql


# ── discover ──────────────────────────────────────────────────────────────────
def test_discover_orders_by_numeric_prefix(tmp_path):
    for name in ('0010_b.sql', '0002_a.sql', '0001_z.sql', 'notes.txt'):
        (tmp_path / name).write_text('SELECT 1;')
    files = db_migrate.discover(str(tmp_path))
    assert [v for v, _, _ in files] == ['0001', '0002', '0010']


def test_discover_missing_dir():
    assert db_migrate.discover('/nonexistent-path-xyz') == []


# ── upgrade decision logic (fake connection) ──────────────────────────────────
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        s = sql.strip().upper()
        if s.startswith('SELECT 1 FROM INFORMATION_SCHEMA.TABLES'):
            self._result = [(1,)] if params[1] in self.conn.tables else []
        elif s.startswith('SELECT VERSION, CHECKSUM'):
            self._result = list(self.conn.applied.items())
        elif s.startswith('INSERT INTO `SCHEMA_MIGRATIONS`'):
            self.conn.applied[params[0]] = params[2]
            self._result = []
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def nextset(self):
        return None


class FakeConn:
    def __init__(self, tables=(), applied=None):
        self.tables = set(tables)
        self.applied = dict(applied or {})
        self.executed = []

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


@pytest.fixture()
def migrations_dir(tmp_path, monkeypatch):
    (tmp_path / '0000_init.sql').write_text('USE `axp`;\nCREATE TABLE roles (id INT);')
    (tmp_path / '0001_next.sql').write_text('ALTER TABLE roles ADD COLUMN x INT;')
    monkeypatch.setattr(db_migrate, 'MIGRATIONS_DIR', str(tmp_path))
    return tmp_path


def _patch_conn(monkeypatch, conn):
    monkeypatch.setattr(db_migrate, '_connect', lambda: conn)


def test_fresh_db_creates_all_and_baselines(monkeypatch, migrations_dir):
    conn = FakeConn(tables={'schema_migrations'})   # roles absent → fresh
    _patch_conn(monkeypatch, conn)
    called = []
    result = db_migrate.upgrade(create_all_fn=lambda: called.append(True))
    assert result['mode'] == 'fresh'
    assert called == [True]
    assert result['baselined'] == ['0000', '0001']
    # nothing was executed from the files themselves
    assert not any('ALTER TABLE' in sql for sql, _ in conn.executed)


def test_existing_db_without_history_baselines(monkeypatch, migrations_dir):
    conn = FakeConn(tables={'roles', 'schema_migrations'})
    _patch_conn(monkeypatch, conn)
    result = db_migrate.upgrade(create_all_fn=lambda: (_ for _ in ()).throw(AssertionError))
    assert result['mode'] == 'baseline'
    assert result['baselined'] == ['0000', '0001']


def test_incremental_applies_only_pending(monkeypatch, migrations_dir):
    files = db_migrate.discover(str(migrations_dir))
    checksum0 = db_migrate._checksum(files[0][2])
    conn = FakeConn(tables={'roles', 'schema_migrations'}, applied={'0000': checksum0})
    _patch_conn(monkeypatch, conn)
    result = db_migrate.upgrade()
    assert result['mode'] == 'incremental'
    assert result['applied'] == ['0001']
    assert any('ALTER TABLE roles' in sql for sql, _ in conn.executed)
    # USE was stripped before execution
    assert not any(sql.strip().upper().startswith('USE ') for sql, _ in conn.executed)


def test_incremental_failure_raises_migration_error(monkeypatch, migrations_dir):
    files = db_migrate.discover(str(migrations_dir))
    checksum0 = db_migrate._checksum(files[0][2])
    conn = FakeConn(tables={'roles', 'schema_migrations'}, applied={'0000': checksum0})

    class BoomCursor(FakeCursor):
        def execute(self, sql, params=None):
            if 'ALTER TABLE' in sql:
                raise RuntimeError('syntax error')
            super().execute(sql, params)

    conn.cursor = lambda: BoomCursor(conn)
    _patch_conn(monkeypatch, conn)
    with pytest.raises(db_migrate.MigrationError) as exc:
        db_migrate.upgrade()
    assert exc.value.version == '0001'
    assert '0001' not in conn.applied   # failed file is not recorded as applied


def test_status_reports_pending(monkeypatch, migrations_dir):
    files = db_migrate.discover(str(migrations_dir))
    checksum0 = db_migrate._checksum(files[0][2])
    conn = FakeConn(tables={'roles', 'schema_migrations'}, applied={'0000': checksum0})
    _patch_conn(monkeypatch, conn)
    s = db_migrate.status()
    assert s == {'applied': ['0000'], 'pending': ['0001']}
