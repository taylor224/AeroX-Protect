from typing import Self

from sqlalchemy import BigInteger, Column, Integer, String

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

RECORD_OFF = 'off'
RECORD_CONTINUOUS = 'continuous'

STRATEGY_LEAST_USED = 'least_used'
STRATEGY_PER_CAMERA = 'per_camera'
STRATEGY_ROUND_ROBIN = 'round_robin'

OVER_DELETE_OLDEST = 'delete_oldest'
OVER_STOP = 'stop_recording'
OVER_WARN = 'warn_only'


class StoragePolicy(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    """Per-camera (or global, camera_id NULL) retention/placement policy (PLAN P2 §4.2)."""
    __tablename__ = 'storage_policies'

    camera_id = Column(BigIntId, nullable=True, index=True)   # NULL = global fallback
    segment_seconds = Column(Integer, nullable=False, default=10)
    container = Column(String(8), nullable=False, default='fmp4')   # fmp4 / mpegts
    record_mode = Column(String(12), nullable=False, default=RECORD_OFF)  # off / continuous
    balance_strategy = Column(String(16), nullable=False, default=STRATEGY_LEAST_USED)
    pinned_disk_id = Column(BigIntId, nullable=True)
    retention_days = Column(Integer, nullable=True)
    retention_max_bytes = Column(BigInteger, nullable=True)
    over_capacity_policy = Column(String(16), nullable=False, default=OVER_DELETE_OLDEST)
    cache_buffer_seconds = Column(Integer, nullable=False, default=60)
    event_retention_days = Column(Integer, nullable=True)   # P3 (column only)

    @classmethod
    def get_global(cls) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id.is_(None), cls.deleted_at.is_(None)).first()

    @classmethod
    def get_for_camera(cls, camera_id: int) -> Self | None:
        """Camera-specific policy, falling back to the global default."""
        row = db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None)).first()
        return row or cls.get_global()

    @classmethod
    def get_raw_for_camera(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_recording_camera_ids(cls) -> list[int]:
        rows = db.session.query(cls.camera_id).filter(
            cls.camera_id.isnot(None), cls.record_mode == RECORD_CONTINUOUS, cls.deleted_at.is_(None)).all()
        return [r[0] for r in rows]

    @classmethod
    def upsert_for_camera(cls, camera_id: int | None, fields: dict, actor_id: int | None = None) -> Self:
        row = db.session.query(cls).filter(cls.camera_id == camera_id if camera_id else cls.camera_id.is_(None),
                                           cls.deleted_at.is_(None)).first()
        if not row:
            row = cls()
            row.camera_id = camera_id
            row.created_by_id = actor_id
        for key, value in fields.items():
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)
        row.last_updated_by_id = actor_id
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'segment_seconds': self.segment_seconds,
            'container': self.container,
            'record_mode': self.record_mode,
            'balance_strategy': self.balance_strategy,
            'pinned_disk_id': str(self.pinned_disk_id) if self.pinned_disk_id else None,
            'retention_days': self.retention_days,
            'retention_max_bytes': self.retention_max_bytes,
            'over_capacity_policy': self.over_capacity_policy,
            'cache_buffer_seconds': self.cache_buffer_seconds,
            'event_retention_days': self.event_retention_days,
        }
