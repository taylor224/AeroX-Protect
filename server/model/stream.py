from typing import Self

from sqlalchemy import Boolean, Column, Integer, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow

ROLE_MAIN = 'main'
ROLE_SUB = 'sub'
ROLE_THIRD = 'third'


def go2rtc_name_for(camera_uuid: str, role: str) -> str:
    """Stable go2rtc stream key (SSOT PLAN §12.1): rtsp://axp-go2rtc:8554/{name}."""
    return 'cam_%s_%s' % (camera_uuid, role)


class Stream(SnowflakeMixin, BaseDB):
    __tablename__ = 'streams'

    camera_id = Column(BigIntId, nullable=False, index=True)
    role = Column(String(16), nullable=False)                  # main/sub/third
    codec = Column(String(16), nullable=True)                  # h264/h265/mjpeg
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    fps = Column(Integer, nullable=True)
    bitrate_kbps = Column(Integer, nullable=True)
    audio_codec = Column(String(16), nullable=True)
    rtsp_path = Column(String(255), nullable=True)             # path only (no credentials)
    rtsp_url_template = Column(String(512), nullable=True)     # rtsp://{user}:{pass}@{host}:{port}{path}
    go2rtc_name = Column(String(128), nullable=False, unique=True, index=True)
    is_default_live = Column(Boolean, nullable=False, default=False)   # grid default (sub)
    is_default_full = Column(Boolean, nullable=False, default=False)   # fullscreen default (main)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime3, nullable=True, index=True)

    @classmethod
    def get_by_camera(cls, camera_id: int) -> list[Self]:
        return db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None)).all()

    @classmethod
    def get_by_go2rtc_name(cls, name: str) -> Self | None:
        return db.session.query(cls).filter(cls.go2rtc_name == name, cls.deleted_at.is_(None)).first()

    @classmethod
    def delete_for_camera(cls, camera_id: int):
        now = utcnow()
        db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None)).update(
            {cls.deleted_at: now}, synchronize_session=False)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'codec': self.codec,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'bitrate_kbps': self.bitrate_kbps,
            'audio_codec': self.audio_codec,
            'rtsp_path': self.rtsp_path,
            'go2rtc_name': self.go2rtc_name,
            'is_default_live': bool(self.is_default_live),
            'is_default_full': bool(self.is_default_full),
            'enabled': bool(self.enabled),
        }
