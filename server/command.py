"""CLI entrypoints (poetry scripts): migrate / seed / seed-admin.

Usage:
    poetry run migrate       # create schema tables from models
    poetry run seed          # seed roles, permission catalog, settings (idempotent)
    poetry run seed-admin    # create first admin from BOOTSTRAP_ADMIN_* (if no users)
"""
import config
from server.model import BaseDB, db


def _ensure_db():
    if db.engine is None:
        db.db_init(config.DATABASE_URI, BaseDB)


def migrate():
    """Create all tables (idempotent — create_all skips existing)."""
    _ensure_db()
    db.create_all()
    print('[migrate] tables created on schema `%s`.' % config.DATABASE_DB)


def seed():
    """Seed system roles, the permission catalog, and default settings."""
    _ensure_db()
    from server.model.permission import PERMISSION_CATALOG, Permission
    from server.model.role import Role
    from server.model.setting import SETTING_SEEDS, Setting

    # roles (reserved ids 1/2 so user.role_id refs are deterministic)
    role_seeds = [
        (1, 'admin', '관리자', {'*': ['*']}, True),
        (2, 'user', '사용자', {}, True),
    ]
    for role_id, name, display_name, permissions, is_system in role_seeds:
        role = Role.get_by_name(name)
        if not role:
            role = Role()
            role.id = role_id
            role.name = name
            role.permissions = permissions
            role.is_system = is_system
            db.session.add(role)
        role.display_name = display_name   # keep system-role labels in sync (self-heals any drift)
    db.session.commit()

    # permission catalog
    created = 0
    for resource, action, description in PERMISSION_CATALOG:
        if not Permission.exists(resource, action):
            perm = Permission()
            perm.resource = resource
            perm.action = action
            perm.description = description
            db.session.add(perm)
            created += 1
    db.session.commit()

    # settings
    for key, value, description in SETTING_SEEDS:
        if Setting.get_value(key, _MISSING) is _MISSING:
            Setting.set_value(key, value, description)

    # default global event policies (P3) — motion records, everything else notifies
    from server.model.event_policy import EventPolicy
    has_global = db.session.query(EventPolicy.id).filter(
        EventPolicy.camera_id.is_(None), EventPolicy.deleted_at.is_(None)).first()
    if not has_global:
        EventPolicy.create({'camera_id': None, 'event_type': 'motion', 'action': 'record',
                            'pre_buffer_s': 5, 'post_buffer_s': 10, 'cooldown_s': 10, 'notify': True})
        EventPolicy.create({'camera_id': None, 'event_type': '*', 'action': 'notify_only', 'notify': True})

    # default AI settings (global row) + builtin detector node (P4)
    from server.model.ai_node import KIND_BUILTIN, AiNode
    from server.model.ai_settings import AiSettings
    AiSettings.ensure_global()
    if not AiNode.get_builtin():
        AiNode.create(name='builtin', kind=KIND_BUILTIN)

    # feature flags (P6) — insert missing keys only; keep admin-set values for existing
    from server.model.feature_flag import FEATURE_FLAG_SEEDS, HIDDEN_FLAG_KEYS, FeatureFlag
    for key, default_enabled, description in FEATURE_FLAG_SEEDS:
        row = FeatureFlag.get(key)
        if not row:
            row = FeatureFlag()
            row.key = key
            row.enabled = default_enabled
            row.description = description
            db.session.add(row)
            continue
        changed = False
        if row.description != description:
            row.description = description           # keep roadmap text fresh
            changed = True
        if key in HIDDEN_FLAG_KEYS and not row.enabled:
            row.enabled = True                     # hidden flags are always-available now
            changed = True
        if changed:
            db.session.add(row)
    db.session.commit()

    print('[seed] roles ok, %d new permissions, settings ok.' % created)


def seed_admin():
    """Create the first admin from BOOTSTRAP_ADMIN_* env. No-op if any user exists."""
    _ensure_db()
    from server.model.role import Role
    from server.model.user import User

    if User.count() > 0:
        print('[seed-admin] users already exist — skipping.')
        return

    if not config.BOOTSTRAP_ADMIN_PW:
        print('[seed-admin] BOOTSTRAP_ADMIN_PW not set — skipping.')
        return

    admin_role = Role.get_by_name('admin')
    if not admin_role:
        seed()
        admin_role = Role.get_by_name('admin')

    user = User.create(
        login_id=config.BOOTSTRAP_ADMIN_ID,
        password=config.BOOTSTRAP_ADMIN_PW,
        name=config.BOOTSTRAP_ADMIN_NAME,
        role_id=admin_role.id,
    )
    print('[seed-admin] created admin "%s" (uuid=%s).' % (user.login_id, user.uuid))


class _Missing:
    pass


_MISSING = _Missing()


if __name__ == '__main__':
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'migrate'
    {'migrate': migrate, 'seed': seed, 'seed-admin': seed_admin}.get(cmd, migrate)()
