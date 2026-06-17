"""Global + per-camera AI settings (PLAN P4 §4.6). Single global row (camera_id NULL) is
the authority for the GPU toggle; per-camera rows override. Effective config = global ←
camera deep-merge (ai_config_resolver)."""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, SmallInteger, String, UniqueConstraint

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

# default detection whitelist (NVR security focus) when ai_settings.labels is NULL
DEFAULT_LABELS = ['person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'dog', 'cat', 'bird']

_FIELDS = ('detection_enabled', 'gpu_enabled', 'model', 'target_fps', 'imgsz', 'min_confidence',
           'labels', 'clip_enabled', 'live_overlay_enabled', 'store_crops', 'retention_days',
           'sample_interval_ms', 'hwaccel', 'audio_enabled', 'audio_threshold')

HWACCELS = ('none', 'auto', 'cuda', 'vaapi', 'qsv', 'videotoolbox')


class AiSettings(SnowflakeMixin, BaseDB):
    __tablename__ = 'ai_settings'
    __table_args__ = (UniqueConstraint('camera_id', name='uq_aiset_cam'),)

    camera_id = Column(BigIntId, nullable=True)        # NULL = global default
    detection_enabled = Column(Boolean, nullable=False, default=True)
    gpu_enabled = Column(Boolean, nullable=False, default=False)   # global authority
    model = Column(String(40), nullable=False, default='yolo11n')   # Ultralytics current flagship
    target_fps = Column(SmallInteger, nullable=False, default=5)
    imgsz = Column(SmallInteger, nullable=False, default=640)
    min_confidence = Column(SmallInteger, nullable=False, default=35)
    labels = Column(JSON, nullable=True)
    clip_enabled = Column(Boolean, nullable=False, default=False)
    live_overlay_enabled = Column(Boolean, nullable=False, default=False)
    store_crops = Column(Boolean, nullable=False, default=False)
    retention_days = Column(SmallInteger, nullable=False, default=30)
    sample_interval_ms = Column(Integer, nullable=False, default=1000)
    hwaccel = Column(String(16), nullable=False, default='none')   # P6 L7 — ffmpeg HW decode
    audio_enabled = Column(Boolean, nullable=False, default=False)  # P6 A4 — audio classification
    audio_threshold = Column(SmallInteger, nullable=False, default=60)  # min score → audio_class event
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)
    last_updated_by_id = Column(BigIntId, nullable=True)

    @classmethod
    def get_global(cls) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id.is_(None)).first()

    @classmethod
    def get_for_camera(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id == camera_id).first()

    @classmethod
    def ensure_global(cls) -> Self:
        row = cls.get_global()
        if row is None:
            row = cls()
            row.camera_id = None
            db.session.add(row)
            db.session.commit()
        return row

    @classmethod
    def upsert(cls, camera_id, data: dict, actor_id=None) -> Self:
        row = cls.get_for_camera(camera_id) if camera_id is not None else cls.get_global()
        if row is None:
            row = cls()
            row.camera_id = camera_id
            if camera_id is not None:                      # seed override from global (coherent)
                g = cls.get_global()
                if g:
                    for f in _FIELDS:
                        setattr(row, f, getattr(g, f))
        for f in _FIELDS:
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        row.last_updated_by_id = actor_id
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'detection_enabled': bool(self.detection_enabled),
            'gpu_enabled': bool(self.gpu_enabled),
            'model': self.model,
            'target_fps': self.target_fps,
            'imgsz': self.imgsz,
            'min_confidence': self.min_confidence,
            'labels': self.labels,
            'clip_enabled': bool(self.clip_enabled),
            'live_overlay_enabled': bool(self.live_overlay_enabled),
            'store_crops': bool(self.store_crops),
            'retention_days': self.retention_days,
            'sample_interval_ms': self.sample_interval_ms,
            'hwaccel': self.hwaccel,
            'audio_enabled': bool(self.audio_enabled),
            'audio_threshold': self.audio_threshold,
            'updated_at': to_epoch_ms(self.updated_at),
        }
