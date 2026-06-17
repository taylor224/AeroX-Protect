import shutil
from typing import Self

from sqlalchemy import BigInteger, Boolean, Column, Integer, String

from server.model import (
    AuditMixin,
    BaseDB,
    DateTime3,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
    utcnow,
)

ROLE_SYSTEM = 'system'
ROLE_CACHE = 'cache'
ROLE_RECORD = 'record'

STATUS_ONLINE = 'online'
STATUS_OFFLINE = 'offline'
STATUS_READONLY = 'readonly'
STATUS_ERROR = 'error'


class Disk(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    """A storage-pool member (PLAN P2 §4.1). cache=pre/post buffer, record=long-term."""
    __tablename__ = 'disks'

    name = Column(String(100), nullable=False)
    mount_path = Column(String(500), nullable=False, unique=True)
    device = Column(String(200), nullable=True)
    fs_uuid = Column(String(100), nullable=True, unique=True)
    role = Column(String(16), nullable=False, default=ROLE_RECORD)
    enabled = Column(Boolean, nullable=False, default=True)
    reserved_free_bytes = Column(BigInteger, nullable=False, default=0)
    total_bytes = Column(BigInteger, nullable=False, default=0)
    free_bytes = Column(BigInteger, nullable=False, default=0)
    weight = Column(Integer, nullable=False, default=100)
    status = Column(String(16), nullable=False, default=STATUS_ONLINE)
    last_seen_at = Column(DateTime3, nullable=True)

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_id(cls, disk_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == disk_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_mount_path(cls, mount_path: str) -> Self | None:
        return db.session.query(cls).filter(cls.mount_path == mount_path, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_fs_uuid(cls, fs_uuid: str) -> Self | None:
        if not fs_uuid:
            return None
        return db.session.query(cls).filter(cls.fs_uuid == fs_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.role, cls.name).all()

    @classmethod
    def get_writable(cls, roles=(ROLE_CACHE, ROLE_RECORD)) -> list[Self]:
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True),
            cls.status == STATUS_ONLINE, cls.role.in_(roles)).all()

    # ── usage ─────────────────────────────────────────────────────────────────
    def refresh_usage(self):
        try:
            usage = shutil.disk_usage(self.mount_path)
            self.total_bytes = usage.total
            self.free_bytes = usage.free
            self.status = STATUS_ONLINE
            self.last_seen_at = utcnow()
        except (FileNotFoundError, PermissionError, OSError):
            self.status = STATUS_OFFLINE
        db.session.add(self)
        db.session.commit()

    @property
    def usable_free_bytes(self) -> int:
        return max(0, (self.free_bytes or 0) - (self.reserved_free_bytes or 0))

    def _health(self, usage_pct: float) -> str:
        """P6 M4 — derived disk health (SMART needs host smartctl; this is usage/reachability)."""
        if self.status in (STATUS_OFFLINE, STATUS_ERROR):
            return 'critical'
        if self.status == STATUS_READONLY:
            return 'warning'
        if usage_pct >= 95:
            return 'critical'
        if usage_pct >= 85:
            return 'warning'
        return 'ok'

    def to_dict(self) -> dict:
        used = (self.total_bytes or 0) - (self.free_bytes or 0)
        usage_pct = round(used / self.total_bytes * 100, 1) if self.total_bytes else 0
        return {
            'id': str(self.id),
            'name': self.name,
            'mount_path': self.mount_path,
            'device': self.device,
            'fs_uuid': self.fs_uuid,
            'role': self.role,
            'enabled': bool(self.enabled),
            'reserved_free_bytes': self.reserved_free_bytes,
            'total_bytes': self.total_bytes,
            'free_bytes': self.free_bytes,
            'used_bytes': used,
            'usage_percent': usage_pct,
            'weight': self.weight,
            'status': self.status,
            'health': self._health(usage_pct),
            'last_seen_at': to_epoch_ms(self.last_seen_at),
        }
