from datetime import timedelta

from flask import g

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import utcnow
from server.model.audit_log import AuditLog
from server.model.camera import Camera
from server.model.recorder_health import RecorderHealth
from server.model.recording import CLASS_PROTECTED, REASON_MANUAL, Recording
from server.model.segment import REASON_MANUAL as SEG_MANUAL, Segment
from server.model import db
from server.model.storage_policy import RECORD_CONTINUOUS, RECORD_OFF, StoragePolicy
from server.service.reconcile import publish_reconcile


class RecordingController:
    @classmethod
    def get_status(cls, camera: Camera) -> dict:
        policy = StoragePolicy.get_for_camera(camera.id)
        health = RecorderHealth.get(camera.id)
        active = Recording.get_active_manual(camera.id)
        return {
            'camera_uuid': camera.uuid,
            'record_mode': policy.record_mode if policy else RECORD_OFF,
            'health': health.to_dict() if health else {'state': 'stopped'},
            'active_manual': active.to_dict() if active else None,
        }

    @classmethod
    def set_mode(cls, camera: Camera, mode: str, actor) -> dict:
        if mode not in (RECORD_OFF, RECORD_CONTINUOUS):
            raise InvalidParameterException('mode must be off or continuous')
        StoragePolicy.upsert_for_camera(camera.id, {'record_mode': mode}, actor.id)
        publish_reconcile(camera.id, 'mode_change')
        AuditLog.record('recording_mode', target=camera.uuid, user_id=actor.id, detail={'mode': mode})
        return cls.get_status(camera)

    @classmethod
    def manual_start(cls, camera: Camera, note: str | None, actor, duration_s: int | None = None) -> dict:
        if Recording.get_active_manual(camera.id):
            raise InvalidParameterException('manual recording already active')
        planned_end = None
        if duration_s is not None:
            duration_s = int(duration_s)
            if duration_s < 5 or duration_s > 24 * 3600:
                raise InvalidParameterException('duration must be 5s–24h')
            planned_end = utcnow() + timedelta(seconds=duration_s)
        rec = Recording.create(camera.id, REASON_MANUAL, CLASS_PROTECTED, utcnow(),
                               end_ts=None, created_by_id=actor.id, note=note, planned_end_ts=planned_end)
        publish_reconcile(camera.id, 'manual_start')   # ensure recorder is running
        AuditLog.record('recording_manual_start', target=camera.uuid, user_id=actor.id,
                        detail={'duration_s': duration_s} if duration_s else None)
        return {'recording_id': str(rec.id), 'start_ts': rec.to_dict()['start_ts'],
                'planned_end_ts': rec.to_dict()['planned_end_ts']}

    @classmethod
    def manual_stop(cls, camera: Camera, recording_id, actor) -> dict:
        rec = Recording.get_by_id(int(recording_id)) if recording_id else Recording.get_active_manual(camera.id)
        if not rec or rec.camera_id != camera.id or rec.reason != REASON_MANUAL or rec.end_ts is not None:
            raise RowNotFoundException()
        cls._close(rec)
        publish_reconcile(camera.id, 'manual_stop')
        AuditLog.record('recording_manual_stop', target=camera.uuid, user_id=actor.id)
        return {'recording_id': str(rec.id), 'end_ts': rec.to_dict()['end_ts']}

    @staticmethod
    def _close(rec: Recording):
        """Close a manual recording + mark its overlapping segments manual (retention)."""
        end = utcnow()
        rec.close(end)
        for seg in Segment.get_range(rec.camera_id, rec.start_ts, end):
            seg.reason = SEG_MANUAL
            db.session.add(seg)
        db.session.commit()

    @classmethod
    def autoclose_due(cls) -> int:
        """Close manual recordings whose fixed duration has elapsed. Returns count closed."""
        due = Recording.due_manual(utcnow())
        for rec in due:
            cls._close(rec)
            publish_reconcile(rec.camera_id, 'manual_autostop')
        return len(due)

    @classmethod
    def protect(cls, recording_id, protected: bool, actor) -> dict:
        """P2 delete-protection toggle for a specific recording (e.g. an event's clip)."""
        rec = Recording.get_by_id(int(recording_id))
        if not rec:
            raise RowNotFoundException()
        # object-level authz: the actor must have scope over the recording's camera —
        # otherwise this is a cross-camera IDOR (e.g. unprotect another camera's evidence)
        from server.service.permission import PermissionService
        cam = Camera.get_by_id(rec.camera_id)
        if cam is None or not PermissionService.has_camera_scope(g.current_user, cam.uuid, 'view'):
            raise NoPermissionException()
        rec.set_protected(protected)
        AuditLog.record('recording_protect', target=str(rec.id), user_id=actor.id,
                        detail={'protected': protected})
        return rec.to_dict()

    @classmethod
    def health_all(cls) -> list[dict]:
        return [h.to_dict() for h in RecorderHealth.get_all()]
