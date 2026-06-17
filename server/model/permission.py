from typing import Self

from sqlalchemy import Column, String, UniqueConstraint

from server.model import BaseDB, DateTime3, SnowflakeMixin, db, utcnow

# Canonical permission catalog (PLAN §12.2, `resource:action`). Phases append rows.
# P0 seeds the full known catalog so the frontend permission editor can render it;
# granting still happens via roles.permissions / users.permissions JSON maps.
PERMISSION_CATALOG: list[tuple[str, str, str]] = [
    # P0
    ('users', 'read', '사용자 조회'),
    ('users', 'create', '사용자 생성'),
    ('users', 'update', '사용자 수정'),
    ('users', 'delete', '사용자 삭제'),
    ('roles', 'read', '역할 조회'),
    ('roles', 'update', '역할 수정'),
    ('roles', 'manage', '역할 관리'),
    ('audit', 'read', '감사로그 조회'),
    ('settings', 'read', '설정 조회'),
    ('settings', 'update', '설정 수정'),
    # P1 (cameras / live / dashboards)
    ('cameras', 'read', '카메라 조회'),
    ('cameras', 'create', '카메라 추가'),
    ('cameras', 'update', '카메라 수정'),
    ('cameras', 'delete', '카메라 삭제'),
    ('cameras', 'discover', '카메라 검색'),
    ('live', 'read', '라이브 보기'),
    ('ptz', 'control', 'PTZ 제어'),
    ('streams', 'read', '스트림 조회'),
    ('streams', 'update', '스트림 수정'),
    ('dashboards', 'read', '대시보드 조회'),
    ('dashboards', 'create', '대시보드 생성'),
    ('dashboards', 'update', '대시보드 수정'),
    ('dashboards', 'delete', '대시보드 삭제'),
    ('dashboards', 'share', '대시보드 공유'),
    # P2 (recording / storage)
    ('recordings', 'read', '녹화 조회'),
    ('recordings', 'control', '녹화 제어'),
    ('playback', 'read', '재생'),
    ('clips', 'export', '클립 내보내기'),
    ('storage', 'read', '스토리지 조회'),
    ('storage', 'manage', '스토리지 관리'),
    ('retention', 'manage', '보존정책 관리'),
    # P3 (events / schedules)
    ('events', 'read', '이벤트 조회'),
    ('events', 'update', '이벤트 수정'),
    ('events', 'delete', '이벤트 삭제'),
    ('policies', 'read', '정책 조회'),
    ('policies', 'update', '정책 수정'),
    ('schedules', 'read', '스케줄 조회'),
    ('schedules', 'update', '스케줄 수정'),
    ('timelapse', 'read', '타임랩스 조회'),
    ('timelapse', 'create', '타임랩스 생성'),
    ('timelapse', 'cancel', '타임랩스 취소'),
    # P4 (AI)
    ('detections', 'read', '검출 조회'),
    ('zones', 'read', '검출구역 조회'),
    ('zones', 'update', '검출구역 수정'),
    ('triggers', 'read', '트리거 조회'),
    ('triggers', 'update', '트리거 수정'),
    ('ai', 'read', 'AI 설정 조회'),
    ('ai', 'update', 'AI 설정 수정'),
    ('ai_nodes', 'manage', 'AI 노드 관리'),
    # P5 (rules / monitors / notifications / api)
    ('rules', 'read', '규칙 조회'),
    ('rules', 'create', '규칙 생성'),
    ('rules', 'update', '규칙 수정'),
    ('rules', 'delete', '규칙 삭제'),
    ('targets', 'read', '대상 조회'),
    ('targets', 'manage', '대상 관리'),
    ('monitors', 'read', '모니터 조회'),
    ('monitors', 'manage', '모니터 관리'),
    ('notifications', 'read', '알림 조회'),
    ('notifications', 'update', '알림 수정'),
    ('api_tokens', 'manage', 'API 토큰 관리'),
    # P6 (advanced features — gated behind feature flags)
    ('feature_flags', 'manage', '기능 플래그 관리'),
    ('bookmarks', 'read', '북마크 조회'),
    ('bookmarks', 'update', '북마크 편집'),
    ('share', 'create', '공유 링크 생성'),
    ('share', 'manage', '공유 링크 관리'),
    ('audio', 'talk', '양방향 오디오 통화'),
    ('ai', 'semantic_search', '시맨틱 검색'),
    ('masks', 'read', '프라이버시 마스크 조회'),
    ('masks', 'update', '프라이버시 마스크 편집'),
    ('archive', 'read', '아카이브 조회'),
    ('archive', 'run', '아카이브 실행·관리'),
    ('maps', 'read', '지도 조회'),
    ('maps', 'update', '지도 편집'),
    ('ai', 'count', '카운팅·배회 설정'),
    ('ai', 'audio', '오디오 분류 조회'),
    # P7 LPR & face
    ('lpr', 'read', '번호판 조회'),
    ('lpr', 'manage', '번호판 워치리스트 관리'),
    ('face', 'read', '얼굴 조회'),
    ('face', 'manage', '얼굴 식별자 관리'),
    # P8 multi-NVR federation
    ('federation', 'read', '연합 조회'),
    ('federation', 'manage', '연합 멤버 관리'),
    # P9 remote portal
    ('portal', 'manage', '원격 포털(TURN) 설정'),
    # P10 access control
    ('access', 'read', '출입 기록 조회'),
    ('access', 'control', '도어 제어(수동 열림/스와이프)'),
    ('access', 'manage', '도어·자격증명 관리'),
]


class Permission(SnowflakeMixin, BaseDB):
    __tablename__ = 'permissions'
    __table_args__ = (UniqueConstraint('resource', 'action', name='uq_permissions_resource_action'),)

    resource = Column(String(50), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    description = Column(String(300), nullable=True)

    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).order_by(cls.resource.asc(), cls.action.asc()).all()

    @classmethod
    def exists(cls, resource: str, action: str) -> bool:
        return db.session.query(cls.id).filter(
            cls.resource == resource, cls.action == action).first() is not None

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'resource': self.resource,
            'action': self.action,
            'description': self.description,
        }
