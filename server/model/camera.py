import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, LargeBinary, String, or_
from sqlalchemy.dialects.mysql import VARBINARY as MYSQL_VARBINARY
from sqlalchemy.orm import relationship, selectinload

from server.exception import RowNotFoundException
from server.model import (
    AuditMixin,
    BaseDB,
    BigIntId,
    DateTime3,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
    utcnow,
)

# Fernet ciphertext column: VARBINARY(512) on MySQL, BLOB elsewhere (sqlite tests).
EncBytes = LargeBinary(512).with_variant(MYSQL_VARBINARY(512), 'mysql')

STATUS_ONLINE = 'online'
STATUS_OFFLINE = 'offline'
STATUS_UNAUTHORIZED = 'unauthorized'
STATUS_ERROR = 'error'
STATUS_UNKNOWN = 'unknown'


class Camera(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'cameras'

    uuid = Column(String(32), nullable=False, unique=True, index=True, default=lambda: uuid_lib.uuid4().hex)
    name = Column(String(200), nullable=False)
    vendor = Column(String(32), nullable=False, default='unknown')   # hikvision/hanwha/onvif/unknown
    model = Column(String(128), nullable=True)
    firmware = Column(String(128), nullable=True)
    serial = Column(String(128), nullable=True, index=True)
    driver = Column(String(32), nullable=False, default='onvif')     # isapi/sunapi/onvif
    protocol_fallback = Column(String(32), nullable=True)

    host = Column(String(255), nullable=False)
    onvif_port = Column(Integer, nullable=True)
    http_port = Column(Integer, nullable=True)
    rtsp_port = Column(Integer, nullable=True)
    rtsp_transport = Column(String(8), nullable=True)               # tcp|udp; NULL = auto (go2rtc native)
    use_https = Column(Boolean, nullable=False, default=False)

    username_enc = Column(EncBytes, nullable=True)
    password_enc = Column(EncBytes, nullable=True)
    cred_key_id = Column(String(32), nullable=True)

    capabilities = Column(JSON, nullable=True)
    ptz_supported = Column(Boolean, nullable=False, default=False)
    audio_supported = Column(Boolean, nullable=False, default=False)
    two_way_audio = Column(Boolean, nullable=False, default=False)
    live_transcode = Column(Boolean, nullable=False, default=False)  # transcode live to H.264 in go2rtc (H.265 cams)
    fisheye = Column(Boolean, nullable=False, default=False)        # P6 L5 — client dewarp
    fisheye_params = Column(JSON, nullable=True)                    # {cx,cy,radius,mode}
    dual_recording = Column(Boolean, nullable=False, default=False)  # P6 R4 — also record sub stream
    dual_record_stream = Column(String(16), nullable=True)          # which stream role to dual-record
    edge_recording = Column(Boolean, nullable=False, default=False)   # P6 R6 — camera has SD for gap-fill import
    edge_auto_import = Column(Boolean, nullable=False, default=False)  # periodically auto-backfill SD gaps
    ai_features = Column(JSON, nullable=True)                        # per-camera AI enables: {audio,smoke,face,lpr}
    channel = Column(Integer, nullable=False, default=1)
    timezone = Column(String(64), nullable=True)

    status = Column(String(16), nullable=False, default=STATUS_UNKNOWN)
    last_seen_at = Column(DateTime3, nullable=True)
    last_error = Column(String(512), nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)

    streams = relationship(
        'Stream',
        primaryjoin='and_(foreign(Stream.camera_id) == Camera.id, Stream.deleted_at == None)',
        viewonly=True,
        order_by='Stream.role',
    )

    # ── credentials (never returned in to_dict) ──────────────────────────────
    def set_credentials(self, username: str | None, password: str | None):
        from server.util import crypto
        if username is not None:
            self.username_enc, self.cred_key_id = crypto.encrypt_credential(username)
        if password is not None:
            self.password_enc, self.cred_key_id = crypto.encrypt_credential(password)

    def get_credentials(self) -> tuple[str | None, str | None]:
        from server.util import crypto
        username = crypto.decrypt_credential(self.username_enc, self.cred_key_id) if self.username_enc else None
        password = crypto.decrypt_credential(self.password_enc, self.cred_key_id) if self.password_enc else None
        return username, password

    @property
    def has_credentials(self) -> bool:
        return self.password_enc is not None

    def ai_feature_on(self, name: str) -> bool:
        """Per-camera AI feature enable (audio/smoke/face/lpr)."""
        return bool((self.ai_features or {}).get(name))

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_uuid(cls, camera_uuid: str) -> Self:
        data = db.session.query(cls).options(selectinload(cls.streams)).filter(
            cls.uuid == camera_uuid, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def get_by_id(cls, camera_id: int) -> Self:
        data = db.session.query(cls).filter(cls.id == camera_id, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def find_duplicate(cls, serial: str | None, host: str, channel: int) -> Self | None:
        query = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if serial:
            dup = query.filter(cls.serial == serial).first()
            if dup:
                return dup
        return query.filter(cls.host == host, cls.channel == channel).first()

    @classmethod
    def get_all_enabled(cls) -> list[Self]:
        return db.session.query(cls).options(selectinload(cls.streams)).filter(
            cls.deleted_at.is_(None), cls.is_enabled.is_(True)).all()

    @classmethod
    def get_list(cls, page, items_per_page, q, sort, order) -> tuple[int, list[Self]]:
        query = db.session.query(cls).options(selectinload(cls.streams)).filter(cls.deleted_at.is_(None))
        if q:
            like = '%{}%'.format(q)
            query = query.filter(or_(cls.name.like(like), cls.host.like(like), cls.model.like(like)))
        sort_col = {'name': cls.name, 'status': cls.status, 'created_at': cls.created_at}.get(sort, cls.created_at)
        sort_col = sort_col.asc() if order == 'asc' else sort_col.desc()
        total = query.count()
        rows = query.order_by(sort_col).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    # ── mutations ─────────────────────────────────────────────────────────────
    def set_status(self, status: str, error: str | None = None):
        self.status = status
        if status == STATUS_ONLINE:
            self.last_seen_at = utcnow()
            self.last_error = None
        elif error:
            self.last_error = error[:512]
        db.session.add(self)
        db.session.commit()

    def soft_delete(self, deleted_by_id: int | None = None):
        self.deleted_at = utcnow()
        self.is_enabled = False
        self.last_updated_by_id = deleted_by_id
        db.session.add(self)
        db.session.commit()

    # ── serialization (credentials excluded) ──────────────────────────────────
    def to_dict(self, with_streams: bool = False, with_capabilities: bool = False) -> dict:
        data = {
            'id': str(self.id),
            'uuid': self.uuid,
            'name': self.name,
            'vendor': self.vendor,
            'model': self.model,
            'firmware': self.firmware,
            'serial': self.serial,
            'driver': self.driver,
            'host': self.host,
            'onvif_port': self.onvif_port,
            'http_port': self.http_port,
            'rtsp_port': self.rtsp_port,
            'rtsp_transport': self.rtsp_transport or 'auto',
            'use_https': bool(self.use_https),
            'channel': self.channel,
            'has_credentials': self.has_credentials,
            'ptz_supported': bool(self.ptz_supported),
            'audio_supported': bool(self.audio_supported),
            'two_way_audio': bool(self.two_way_audio),
            'live_transcode': bool(self.live_transcode),
            'fisheye': bool(self.fisheye),
            'fisheye_params': self.fisheye_params,
            'dual_recording': bool(self.dual_recording),
            'dual_record_stream': self.dual_record_stream,
            'edge_recording': bool(self.edge_recording),
            'edge_auto_import': bool(self.edge_auto_import),
            'ai_features': self.ai_features or {},
            'status': self.status,
            'last_seen_at': to_epoch_ms(self.last_seen_at),
            'last_error': self.last_error,
            'is_enabled': bool(self.is_enabled),
            'created_at': to_epoch_ms(self.created_at),
            'updated_at': to_epoch_ms(self.updated_at),
        }
        if with_streams:
            data['streams'] = [s.to_dict() for s in self.streams]
        if with_capabilities:
            data['capabilities'] = self.capabilities
        return data
