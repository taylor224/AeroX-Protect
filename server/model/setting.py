from typing import Self

from sqlalchemy import JSON, Column, String

from server.model import BaseDB, DateTime3, SnowflakeMixin, db, utcnow

# Global key/value settings. No soft delete.
# NOTE (PLAN §12.1): `gpu_enabled` here is a bootstrap placeholder only — the
# authoritative global GPU toggle is P4 `ai_settings.gpu_enabled`.
SETTING_SEEDS: list[tuple[str, object, str]] = [
    ('gpu_enabled', False, '전역 GPU 사용 (P4에서 ai_settings로 이관)'),
    ('timezone', 'Asia/Seoul', '표시 시간대'),
    ('retention_default_days', 30, '기본 보존 기간(일)'),
]


class Setting(SnowflakeMixin, BaseDB):
    __tablename__ = 'settings'

    key = Column(String(120), nullable=False, unique=True, index=True)
    value = Column(JSON, nullable=True)
    description = Column(String(300), nullable=True)

    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_value(cls, key: str, default=None):
        row = db.session.query(cls).filter(cls.key == key).first()
        return row.value if row else default

    @classmethod
    def set_value(cls, key: str, value, description: str | None = None) -> Self:
        row = db.session.query(cls).filter(cls.key == key).first()
        if not row:
            row = cls()
            row.key = key
            if description is not None:
                row.description = description
        row.value = value
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).order_by(cls.key.asc()).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'key': self.key,
            'value': self.value,
            'description': self.description,
        }
