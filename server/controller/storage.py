import os

from server.exception import ConflictException, InvalidParameterException, RowNotFoundException
from server.model import db
from server.model.audit_log import AuditLog
from server.model.disk import Disk
from server.model.storage_policy import RECORD_CONTINUOUS, RECORD_OFF, StoragePolicy
from server.service import disk_scanner, retention_engine, storage_manager
from server.service.reconcile import publish_reconcile
from server.util.tool import safe_int

_VALID_ROLES = ('system', 'cache', 'record')


class StorageController:
    # ── disks ─────────────────────────────────────────────────────────────────
    @classmethod
    def list_disks(cls) -> list[dict]:
        disks = Disk.get_all()
        for d in disks:
            d.refresh_usage()
        return [d.to_dict() for d in disks]

    @classmethod
    def create_disk(cls, data: dict, actor) -> dict:
        mount_path = (data.get('mount_path') or '').strip()
        name = (data.get('name') or '').strip()
        role = data.get('role') or 'record'
        if not mount_path or not name:
            raise InvalidParameterException('mount_path and name are required')
        if role not in _VALID_ROLES:
            raise InvalidParameterException('invalid role')
        if not os.path.isdir(mount_path):
            raise InvalidParameterException('mount_path is not a directory')
        if not disk_scanner.write_verify(mount_path):
            raise InvalidParameterException('mount_path is not writable')
        if Disk.get_by_mount_path(mount_path):
            raise ConflictException('disk already registered')

        disk = Disk()
        disk.name = name
        disk.mount_path = mount_path
        disk.device = data.get('device')
        disk.fs_uuid = data.get('fs_uuid') or None
        disk.role = role
        disk.enabled = bool(data.get('enabled', True))
        disk.reserved_free_bytes = safe_int(data.get('reserved_free_bytes'), 0)
        disk.weight = safe_int(data.get('weight'), 100)
        disk.created_by_id = actor.id
        disk.last_updated_by_id = actor.id
        db.session.add(disk)
        db.session.commit()
        disk.refresh_usage()
        AuditLog.record('disk_registered', target=str(disk.id), user_id=actor.id, detail={'mount_path': mount_path})
        return disk.to_dict()

    @classmethod
    def update_disk(cls, disk_id: int, data: dict, actor) -> dict:
        disk = Disk.get_by_id(disk_id)
        if not disk:
            raise RowNotFoundException()
        if data.get('name') is not None:
            disk.name = data['name']
        if data.get('role') in _VALID_ROLES:
            disk.role = data['role']
        if 'enabled' in data:
            disk.enabled = bool(data['enabled'])
        if data.get('reserved_free_bytes') is not None:
            disk.reserved_free_bytes = safe_int(data['reserved_free_bytes'], 0)
        if data.get('weight') is not None:
            disk.weight = safe_int(data['weight'], 100)
        disk.last_updated_by_id = actor.id
        db.session.add(disk)
        db.session.commit()
        return disk.to_dict()

    @classmethod
    def delete_disk(cls, disk_id: int, mode: str, actor):
        disk = Disk.get_by_id(disk_id)
        if not disk:
            raise RowNotFoundException()
        if mode == 'evacuate':
            from server.task.list.segment_sweep import evacuate_disk
            evacuate_disk.delay(str(disk.id))
            AuditLog.record('disk_evacuate', target=str(disk.id), user_id=actor.id)
            return {'mode': 'evacuate', 'status': 'queued'}
        # unregister: drop the disk row (segments index remains; sweep flags orphans)
        from server.model import utcnow
        disk.deleted_at = utcnow()
        disk.enabled = False
        db.session.add(disk)
        db.session.commit()
        AuditLog.record('disk_unregistered', target=str(disk.id), user_id=actor.id)
        return {'mode': 'unregister', 'status': 'done'}

    @classmethod
    def discover(cls) -> list[dict]:
        return disk_scanner.discover_candidates()

    @classmethod
    def pool(cls) -> dict:
        return storage_manager.pool_summary()

    # ── policies ──────────────────────────────────────────────────────────────
    @classmethod
    def get_policies(cls) -> dict:
        from server.model.camera import Camera
        global_pol = StoragePolicy.get_global()
        per_camera = {}
        for cam in Camera.get_all_enabled():
            raw = StoragePolicy.get_raw_for_camera(cam.id)
            if raw:
                per_camera[cam.uuid] = raw.to_dict()
        return {'global': global_pol.to_dict() if global_pol else None, 'cameras': per_camera}

    @classmethod
    def get_policy(cls, camera_id: int | None) -> dict:
        pol = StoragePolicy.get_for_camera(camera_id) if camera_id else StoragePolicy.get_global()
        return pol.to_dict() if pol else {}

    @classmethod
    def update_policy(cls, camera_id: int | None, data: dict, actor) -> dict:
        allowed = {'segment_seconds', 'container', 'record_mode', 'balance_strategy', 'pinned_disk_id',
                   'retention_days', 'retention_max_bytes', 'over_capacity_policy', 'cache_buffer_seconds',
                   'event_retention_days'}
        fields = {k: v for k, v in data.items() if k in allowed}
        if fields.get('record_mode') not in (None, RECORD_OFF, RECORD_CONTINUOUS):
            raise InvalidParameterException('invalid record_mode')

        prev = StoragePolicy.get_raw_for_camera(camera_id) if camera_id else StoragePolicy.get_global()
        prev_mode = prev.record_mode if prev else RECORD_OFF
        pol = StoragePolicy.upsert_for_camera(camera_id, fields, actor.id)

        warnings = retention_engine.check_pool_overcommit(
            {'retention_max_bytes': fields.get('retention_max_bytes')} if fields.get('retention_max_bytes') else None)

        if camera_id and pol.record_mode != prev_mode:
            publish_reconcile(camera_id, 'mode_change')

        result = pol.to_dict()
        result['warnings'] = warnings
        return result
