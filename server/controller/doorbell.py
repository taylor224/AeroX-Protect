"""Doorbell / intercom (PLAN P6 M3). A SIP/ONVIF doorbell adapter (or test) POSTs a ring;
we raise a `doorbell_call` event through the normal pipeline (→ outbox → rules/notify). The
frontend watches for it and opens a call UI (answer via L1 two-way audio). Flag `doorbell`.
"""
from server.exception import NoPermissionException
from server.model.camera import Camera
from server.model.event import TYPE_DOORBELL
from server.service import event_pipeline, feature_flag
from server.service.permission import PermissionService


class DoorbellController:
    @classmethod
    def ring(cls, user, camera_uuid: str, data: dict) -> dict:
        if not feature_flag.is_enabled('doorbell'):
            raise NoPermissionException('feature_disabled')
        camera = Camera.get_by_uuid(camera_uuid)                # raises → 404
        if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        ev = event_pipeline.ingest_object(camera.id, {
            'type': TYPE_DOORBELL, 'state': 'pulse',
            'subtype': data.get('subtype') or 'doorbell', 'source': 'doorbell'})
        return {'event_id': str(ev.id) if ev else None, 'camera_uuid': camera.uuid}
