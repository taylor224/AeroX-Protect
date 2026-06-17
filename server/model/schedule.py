from typing import Self

from sqlalchemy import Boolean, Column, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db, utcnow

MODE_CONTINUOUS = 'continuous'
MODE_EVENT = 'event'
MODE_MOTION_ONLY = 'motion_only'
MODE_OFF = 'off'
MODES = (MODE_CONTINUOUS, MODE_EVENT, MODE_MOTION_ONLY, MODE_OFF)


class Schedule(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    """Per-camera weekly recording schedule rule (PLAN §4.3). day_of_week 0=Mon..6=Sun (KST)."""
    __tablename__ = 'schedules'

    camera_id = Column(BigIntId, nullable=False, index=True)
    name = Column(String(80), nullable=True)
    day_of_week = Column(SmallInteger, nullable=False)
    start_min = Column(SmallInteger, nullable=False)    # 0..1439
    end_min = Column(SmallInteger, nullable=False)      # 1..1440
    mode = Column(String(16), nullable=False)
    priority = Column(SmallInteger, nullable=False, default=0)
    timezone = Column(String(40), nullable=False, default='Asia/Seoul')
    enabled = Column(Boolean, nullable=False, default=True)
    group_uuid = Column(String(40), nullable=True)

    @classmethod
    def get_for_camera(cls, camera_id: int) -> list[Self]:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.deleted_at.is_(None), cls.enabled.is_(True)).all()

    @classmethod
    def get_for_camera_dow(cls, camera_id: int, day_of_week: int) -> list[Self]:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.day_of_week == day_of_week,
            cls.deleted_at.is_(None), cls.enabled.is_(True)).all()

    @classmethod
    def replace_for_camera(cls, camera_id: int, rules: list[dict], actor_id=None) -> list[Self]:
        """Full replace of a camera's rules."""
        db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None)).update(
            {cls.deleted_at: utcnow()}, synchronize_session=False)
        created = []
        for rule in rules:
            r = cls()
            r.camera_id = camera_id
            r.name = rule.get('name')
            r.day_of_week = int(rule['day_of_week'])
            r.start_min = int(rule['start_min'])
            r.end_min = int(rule['end_min'])
            r.mode = rule['mode']
            r.priority = int(rule.get('priority', 0))
            r.timezone = rule.get('timezone', 'Asia/Seoul')
            r.group_uuid = rule.get('group_uuid')
            r.created_by_id = actor_id
            r.last_updated_by_id = actor_id
            db.session.add(r)
            created.append(r)
        db.session.commit()
        return created

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'day_of_week': self.day_of_week,
            'start_min': self.start_min,
            'end_min': self.end_min,
            'mode': self.mode,
            'priority': self.priority,
            'timezone': self.timezone,
            'group_uuid': self.group_uuid,
        }
