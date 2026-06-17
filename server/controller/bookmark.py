"""Bookmark CRUD (PLAN P6 R2). Camera-scoped: every read/write checks the caller's
camera_scope ∩ the bookmark's camera. `lock_retention` best-effort protects the linked
recording (P2 retention) so the marked footage survives purge.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.bookmark import Bookmark
from server.model.camera import Camera
from server.model.recording import CLASS_PROTECTED, Recording
from server.service import feature_flag
from server.service.permission import PermissionService


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard_flag():
    if not feature_flag.is_enabled('bookmarks'):
        raise NoPermissionException('feature_disabled')


def _scoped_camera(user, camera_uuid: str) -> Camera:
    if not camera_uuid:
        raise InvalidParameterException('camera_uuid required')
    camera = Camera.get_by_uuid(camera_uuid)          # raises RowNotFoundException if missing
    if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
        raise NoPermissionException('camera_scope_denied')
    return camera


def _protect_recording(recording_id):
    if not recording_id:
        return
    rec = db_recording(recording_id)
    if rec and rec.retention_class != CLASS_PROTECTED:
        rec.retention_class = CLASS_PROTECTED
        from server.model import db
        db.session.add(rec)
        db.session.commit()


def db_recording(recording_id):
    from server.model import db
    return db.session.query(Recording).filter(Recording.id == recording_id).first()


class BookmarkController:
    @classmethod
    def list_bookmarks(cls, user, args) -> dict:
        _guard_flag()
        camera = _scoped_camera(user, args.get('camera_uuid') or args.get('camera_id'))
        rows = Bookmark.list_for_camera(camera.id, _parse_ms(args.get('start')), _parse_ms(args.get('end')))
        return {'count': len(rows), 'items': [b.to_dict() for b in rows]}

    @classmethod
    def create(cls, user, data: dict) -> dict:
        _guard_flag()
        camera = _scoped_camera(user, data.get('camera_uuid'))
        start_ts = _parse_ms(data.get('start_ts'))
        if start_ts is None:
            raise InvalidParameterException('start_ts required')
        end_ts = _parse_ms(data.get('end_ts'))
        if end_ts is not None and end_ts < start_ts:
            raise InvalidParameterException('end_ts before start_ts')
        label = (data.get('label') or '').strip()
        if not label:
            raise InvalidParameterException('label required')

        lock = bool(data.get('lock_retention'))
        rec_id = _to_int(data.get('recording_id'))
        b = Bookmark.create(
            camera.id, start_ts, label, end_ts=end_ts,
            color=data.get('color'), note=data.get('note'),
            recording_id=rec_id, event_id=_to_int(data.get('event_id')),
            lock_retention=lock, actor_id=user.id)
        if lock:
            _protect_recording(rec_id)
        return b.to_dict()

    @classmethod
    def update(cls, user, bookmark_id, data: dict) -> dict:
        _guard_flag()
        b = cls._require(user, bookmark_id)
        fields = {}
        for f in ('label', 'color', 'note', 'lock_retention'):
            if f in data:
                fields[f] = data[f]
        if 'end_ts' in data:
            fields['end_ts'] = _parse_ms(data.get('end_ts'))
        if 'start_ts' in data and _parse_ms(data.get('start_ts')) is not None:
            fields['start_ts'] = _parse_ms(data.get('start_ts'))
        if fields:
            b.update(actor_id=user.id, **fields)
        if data.get('lock_retention'):
            _protect_recording(b.recording_id)
        return b.to_dict()

    @classmethod
    def delete(cls, user, bookmark_id):
        _guard_flag()
        cls._require(user, bookmark_id).soft_delete()

    @staticmethod
    def _require(user, bookmark_id) -> Bookmark:
        b = Bookmark.get_by_id(bookmark_id)
        if not b:
            raise RowNotFoundException()
        camera = Camera.get_by_id(b.camera_id)
        if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        return b


def _to_int(value):
    try:
        return int(value) if value not in (None, '') else None
    except (ValueError, TypeError):
        return None
