import secrets
from datetime import datetime, timedelta
from typing import Self

from sqlalchemy import BigInteger, Boolean, Column, Integer, LargeBinary, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

STATUS_QUEUED = 'queued'
STATUS_PROCESSING = 'processing'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_EXPIRED = 'expired'

MODE_COPY = 'copy'
MODE_TRANSCODE = 'transcode'


class ExportJob(SnowflakeMixin, BaseDB):
    """Clip export / transcode job (PLAN P2 §4.5)."""
    __tablename__ = 'export_jobs'

    camera_id = Column(BigIntId, nullable=False)
    requested_by_id = Column(BigIntId, nullable=False)
    start_ts = Column(DateTime3, nullable=False)
    end_ts = Column(DateTime3, nullable=False)
    mode = Column(String(12), nullable=False, default=MODE_COPY)
    container = Column(String(8), nullable=False, default='mp4')
    transcode_preset = Column(String(50), nullable=True)
    watermark = Column(Boolean, nullable=False, default=False)      # P6 R3 — burned drawtext
    watermark_text = Column(String(200), nullable=True)
    password_protected = Column(Boolean, nullable=False, default=False)  # P6 R3 — AES zip
    enc_password = Column(LargeBinary, nullable=True)              # Fernet ciphertext (never plaintext)
    enc_key_id = Column(String(50), nullable=True)
    status = Column(String(12), nullable=False, default=STATUS_QUEUED)
    progress = Column(Integer, nullable=False, default=0)
    celery_task_id = Column(String(100), nullable=True)
    output_disk_id = Column(BigIntId, nullable=True)
    output_rel_path = Column(String(500), nullable=True)
    output_size_bytes = Column(BigInteger, nullable=True)
    download_token = Column(String(100), nullable=False, unique=True)
    error_message = Column(String(1000), nullable=True)
    expires_at = Column(DateTime3, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_by_id(cls, job_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == job_id).first()

    @classmethod
    def get_by_token(cls, token: str) -> Self | None:
        return db.session.query(cls).filter(cls.download_token == token).first()

    @classmethod
    def list_for_user(cls, user_id: int, page: int, items_per_page: int) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.requested_by_id == user_id).order_by(cls.created_at.desc())
        total = q.count()
        return total, q.limit(items_per_page).offset((page - 1) * items_per_page).all()

    @classmethod
    def get_expired(cls, now: datetime, limit: int = 100) -> list[Self]:
        return db.session.query(cls).filter(
            cls.expires_at.isnot(None), cls.expires_at < now,
            cls.status.in_([STATUS_DONE, STATUS_FAILED])).limit(limit).all()

    @classmethod
    def create(cls, camera_id, requested_by_id, start_ts, end_ts, mode, container='mp4',
               transcode_preset=None, watermark=False, watermark_text=None,
               password_protected=False, enc_password=None, enc_key_id=None) -> Self:
        job = cls()
        job.camera_id = camera_id
        job.requested_by_id = requested_by_id
        job.start_ts = start_ts
        job.end_ts = end_ts
        job.mode = mode
        job.container = container
        job.transcode_preset = transcode_preset
        job.watermark = bool(watermark)
        job.watermark_text = watermark_text
        job.password_protected = bool(password_protected)
        job.enc_password = enc_password
        job.enc_key_id = enc_key_id
        job.download_token = secrets.token_urlsafe(32)
        job.expires_at = utcnow() + timedelta(hours=24)
        db.session.add(job)
        db.session.commit()
        return job

    def update(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)
        db.session.add(self)
        db.session.commit()

    def to_dict(self, with_token: bool = False) -> dict:
        data = {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'start_ts': to_epoch_ms(self.start_ts),
            'end_ts': to_epoch_ms(self.end_ts),
            'mode': self.mode,
            'container': self.container,
            'transcode_preset': self.transcode_preset,
            'watermark': bool(self.watermark),
            'password_protected': bool(self.password_protected),
            'status': self.status,
            'progress': self.progress,
            'output_size_bytes': self.output_size_bytes,
            'error_message': self.error_message,
            'expires_at': to_epoch_ms(self.expires_at),
            'created_at': to_epoch_ms(self.created_at),
        }
        if with_token and self.status == STATUS_DONE:
            data['download_token'] = self.download_token
        return data
