"""Feature flags (PLAN P6 §4.1, DoD §9 횡단): per-key on/off toggles so every P6
advanced feature ships dark and can be enabled without code change. `flag off = cost 0`
(§13) — gates sit at API entry / page load, never in hot loops.

Scope is global for now (camera_id NULL); the (key, camera_id) unique pair leaves room
for per-camera overrides later. Seeds below are the P6 roadmap: implemented features
default ON, not-yet-built ones default OFF so the admin panel doubles as a roadmap.
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, String, UniqueConstraint

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

SCOPE_GLOBAL = 'global'
SCOPE_CAMERA = 'camera'

# (key, default_enabled, description). seed() upserts new keys idempotently; existing
# rows keep their admin-set value (only missing keys are inserted).
FEATURE_FLAG_SEEDS: list[tuple[str, bool, str]] = [
    # Wave 1 — implemented (default ON)
    ('bookmarks', True, '타임라인 북마크/라벨 (R2)'),
    ('batch_camera_add', True, '배치 카메라 추가 (M1)'),
    ('live_sequence', True, '시퀀스/이벤트 자동전환 (L3/L4)'),
    ('share_links', True, '공유 링크 사용가능 (R1) — 사용자가 공유 링크를 만들 수 있는지'),
    ('semantic_search', True, '시맨틱 검색 (A1 — CLIP 있으면 이미지, 없으면 텍스트)'),
    ('two_way_audio', True, '양방향 오디오 (L1 — 카메라 backchannel 지원 시)'),
    # Wave 2 — implemented (default ON)
    ('privacy_masks', True, '프라이버시 마스킹 (L2)'),
    ('export_watermark', True, '내보내기 워터마크/비밀번호 (R3)'),
    ('maps', True, '지도 기반 모니터링 (L6)'),
    # Wave 2+ — roadmap surface
    ('sms_notifications', True, 'SMS 알림 (N1 — Twilio)'),
    ('archiving', True, '백업·아카이빙 (M2 — S3/SMB/local)'),
    ('object_counting', True, '사람/차량 카운팅·occupancy (A2)'),
    ('loitering', True, '배회 감지 (A3)'),
    ('doorbell', True, '도어벨/인터컴 (M3)'),
    # Wave 3 — implemented (opt-in per camera; flag gates the UI toggle)
    ('dual_recording', True, '이중 녹화 — 서브 스트림 동시 저장 (R4, 카메라별 opt-in)'),
    ('edge_recording', True, '엣지 녹화 임포트 — 카메라 SD 갭필 (R6, 카메라별 opt-in)'),
    ('audio_detection', True, '오디오 분류 — 유리깨짐/비명/경보 등 (A4, 모델 있으면 PANNs)'),
    ('smoke_detection', False, '연기/화재 보조 알림 (A5 — 전용 모델 필요, 기본 OFF·면책 고지)'),
    # P7 — LPR & face (need dedicated models; default OFF, opt-in)
    ('lpr', False, '번호판 인식 (P7 A7 — 전용 OCR 모델 필요, 워치리스트 매칭)'),
    ('face', False, '얼굴 인식 (P7 A8 — 전용 임베딩 모델 필요, 동의·보존 정책)'),
    # P8 — multi-NVR federation (hub aggregating member NVRs)
    ('federation', False, '다중 NVR 연합 (P8 — 멤버 NVR의 카메라/이벤트 집계)'),
    # P9 — remote portal: outside-LAN viewing works by default over the TURN-free MSE/WebSocket
    # path; this flag just exposes the optional TURN relay config (for WebRTC through hard NATs).
    ('remote_portal', True, '원격 포털 (P9 — 선택적 TURN 릴레이 설정; 기본 원격 보기는 WebSocket으로 동작)'),
    # P10 — access control (doors, credentials, access events)
    ('access_control', True, '출입 통제 (P10 — 도어 컨트롤러/카드, 하드웨어 필요)'),
]

# Flags hidden from the Settings → Feature-flags list. They're now always-available and
# controlled by their natural place instead of a global on/off:
#  • bookmarks = always on (basic feature)
#  • archiving / access_control / export_watermark / sms_notifications = config-driven
#    (set up an archive target / a door / export options / Twilio) → it just works
#  • two_way_audio / privacy_masks / object_counting / loitering / dual_recording /
#    edge_recording = per-camera settings
# `enabled_map()` still returns them (useFeatureFlag works); only the admin LIST hides them.
HIDDEN_FLAG_KEYS = {
    'bookmarks', 'two_way_audio', 'privacy_masks', 'export_watermark', 'sms_notifications',
    'archiving', 'object_counting', 'loitering', 'dual_recording', 'edge_recording',
    'access_control',
    # always-on basics / config-driven (controlled by their natural place, not a global toggle)
    'batch_camera_add',   # always available
    'doorbell',           # always available (SIP/ONVIF doorbell just works when one calls in)
    'maps',               # always available
    'live_sequence',      # moved to PER-DASHBOARD config (auto-switch pages)
    'remote_portal',      # remote viewing works by default (WS); TURN config shown to admins
    # AI features now enabled PER CAMERA (cameras.ai_features) — not a global flag
    'audio_detection', 'smoke_detection', 'face', 'lpr',
}


class FeatureFlag(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'feature_flags'
    __table_args__ = (UniqueConstraint('key', 'camera_id', name='uq_feature_flags_key_camera'),)

    key = Column(String(80), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    scope = Column(String(16), nullable=False, default=SCOPE_GLOBAL)
    camera_id = Column(BigIntId, nullable=True)
    value = Column(JSON, nullable=True)
    description = Column(String(300), nullable=True)

    @classmethod
    def get(cls, key: str, camera_id: int | None = None) -> Self | None:
        q = db.session.query(cls).filter(cls.key == key, cls.deleted_at.is_(None))
        q = q.filter(cls.camera_id == camera_id) if camera_id else q.filter(cls.camera_id.is_(None))
        return q.first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return (db.session.query(cls)
                .filter(cls.deleted_at.is_(None))
                .order_by(cls.key.asc()).all())

    @classmethod
    def set_enabled(cls, key: str, enabled: bool, value=None, actor_id=None) -> Self:
        row = cls.get(key)
        if not row:
            row = cls()
            row.key = key
            row.scope = SCOPE_GLOBAL
            row.created_by_id = actor_id
        row.enabled = bool(enabled)
        if value is not None:
            row.value = value
        row.last_updated_by_id = actor_id
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'enabled': bool(self.enabled),
            'scope': self.scope,
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'value': self.value,
            'description': self.description,
        }
