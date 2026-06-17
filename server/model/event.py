from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Integer, SmallInteger, String, and_, or_
from sqlalchemy.orm import selectinload  # noqa: F401 (reserved for DTO joins)

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

# state
STATE_ACTIVE = 0       # start received, in progress
STATE_ENDED = 1
STATE_PULSE = 2        # single-shot, no start/end distinction

# normalized types (PLAN §6.4)
TYPE_MOTION = 'motion'
TYPE_LINE_CROSSING = 'line_crossing'
TYPE_INTRUSION = 'intrusion'
TYPE_REGION_ENTER = 'region_enter'
TYPE_REGION_EXIT = 'region_exit'
TYPE_TAMPER = 'tamper'
TYPE_AUDIO = 'audio'
TYPE_IO = 'io'
TYPE_VIDEO_LOSS = 'video_loss'
TYPE_OBJECT = 'object'      # P4
TYPE_LOITERING = 'loitering'  # P6 A3
TYPE_COUNT = 'count'          # P6 A2 — line crossing count
TYPE_OCCUPANCY = 'occupancy'  # P6 A2 — region occupancy
TYPE_DOORBELL = 'doorbell_call'  # P6 M3
TYPE_AUDIO_CLASS = 'audio_class'  # P6 A4 — classified audio (glass break/scream/alarm…)
TYPE_SMOKE = 'smoke'              # P6 A5 — smoke/fire (auxiliary alert; needs dedicated model)
TYPE_LPR = 'lpr'                  # P7 A7 — license-plate read (watchlist hit)
TYPE_FACE = 'face'                # P7 A8 — face match (known identity)
TYPE_ACCESS = 'access'            # P10 — door access (granted/denied)
TYPE_UNKNOWN = 'unknown'


class Event(SnowflakeMixin, BaseDB):
    __tablename__ = 'events'

    camera_id = Column(BigIntId, nullable=False)
    type = Column(String(32), nullable=False)
    subtype = Column(String(48), nullable=True)
    state = Column(SmallInteger, nullable=False, default=STATE_PULSE)
    start_ts = Column(DateTime3, nullable=False)
    end_ts = Column(DateTime3, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    score = Column(SmallInteger, nullable=True)
    source = Column(String(16), nullable=False)
    channel = Column(SmallInteger, nullable=True)
    region = Column(JSON, nullable=True)
    snapshot_path = Column(String(512), nullable=True)
    recording_id = Column(BigIntId, nullable=True)
    policy_action = Column(String(16), nullable=True)
    dedup_key = Column(String(80), nullable=False)
    vendor_event_id = Column(String(128), nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    deleted_at = Column(DateTime3, nullable=True)

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_id(cls, event_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == event_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def exists_vendor(cls, camera_id: int, vendor_event_id: str) -> bool:
        return db.session.query(cls.id).filter(
            cls.camera_id == camera_id, cls.vendor_event_id == vendor_event_id).first() is not None

    @classmethod
    def get_active_by_dedup(cls, dedup_key: str) -> Self | None:
        return db.session.query(cls).filter(
            cls.dedup_key == dedup_key, cls.state == STATE_ACTIVE, cls.deleted_at.is_(None)
        ).order_by(cls.start_ts.desc()).first()

    @classmethod
    def get_stale_active(cls, older_than: datetime, limit: int = 500) -> list[Self]:
        return db.session.query(cls).filter(
            cls.state == STATE_ACTIVE, cls.start_ts < older_than, cls.deleted_at.is_(None)
        ).limit(limit).all()

    @classmethod
    def get_list(cls, *, camera_ids=None, types=None, subtype=None, start=None, end=None,
                 min_score=None, has_recording=None, state=None, page=1, items_per_page=20,
                 sort='start_ts', order='desc') -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if camera_ids:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if types:
            q = q.filter(cls.type.in_(types))
        if subtype:
            q = q.filter(cls.subtype == subtype)
        if start is not None:
            q = q.filter(cls.start_ts >= start)
        if end is not None:
            q = q.filter(cls.start_ts <= end)
        if min_score is not None:
            q = q.filter(cls.score >= min_score)
        if has_recording is True:
            q = q.filter(cls.recording_id.isnot(None))
        elif has_recording is False:
            q = q.filter(cls.recording_id.is_(None))
        if state is not None:
            q = q.filter(cls.state == state)

        sort_col = cls.start_ts if sort == 'start_ts' else getattr(cls, sort, cls.start_ts)
        q = q.order_by(sort_col.asc() if order == 'asc' else sort_col.desc())
        total = q.count()
        rows = q.limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    @classmethod
    def get_markers(cls, camera_id: int, start: datetime, end: datetime, types=None) -> list[Self]:
        q = db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.deleted_at.is_(None),
            cls.start_ts >= start, cls.start_ts <= end)
        if types:
            q = q.filter(cls.type.in_(types))
        return q.order_by(cls.start_ts.asc()).all()

    # ── mutations ─────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, camera_id, type, source, dedup_key, start_ts, state=STATE_PULSE,
               subtype=None, score=None, channel=None, region=None, vendor_event_id=None,
               raw=None) -> Self:
        ev = cls()
        ev.camera_id = camera_id
        ev.type = type
        ev.source = source
        ev.dedup_key = dedup_key
        ev.start_ts = start_ts
        ev.state = state
        ev.subtype = subtype
        ev.score = score
        ev.channel = channel
        ev.region = region
        ev.vendor_event_id = vendor_event_id
        ev.raw = raw
        db.session.add(ev)
        db.session.commit()
        return ev

    def close(self, end_ts: datetime):
        self.end_ts = end_ts
        self.state = STATE_ENDED
        if self.start_ts and end_ts:
            self.duration_ms = max(0, int((end_ts - self.start_ts).total_seconds() * 1000))
        db.session.add(self)
        db.session.commit()

    def soft_delete(self):
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def to_dict(self, with_raw: bool = False) -> dict:
        data = {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'type': self.type,
            'subtype': self.subtype,
            'state': self.state,
            'start_ts': to_epoch_ms(self.start_ts),
            'end_ts': to_epoch_ms(self.end_ts),
            'duration_ms': self.duration_ms,
            'score': self.score,
            'source': self.source,
            'channel': self.channel,
            'region': self.region,
            'recording_id': str(self.recording_id) if self.recording_id else None,
            'policy_action': self.policy_action,
            'created_at': to_epoch_ms(self.created_at),
        }
        if with_raw:
            data['raw'] = self.raw
        return data

    def to_ws_dict(self) -> dict:
        return {'id': str(self.id), 'camera_id': str(self.camera_id), 'type': self.type,
                'start_ts': to_epoch_ms(self.start_ts), 'score': self.score}
