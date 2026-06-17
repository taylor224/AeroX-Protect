import os
import subprocess
from datetime import datetime

from server.exception import NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.camera import Camera
from server.model.detection import Detection
from server.model.disk import Disk
from server.model.segment import Segment
from server.service import detection_search, ffmpeg, playback_planner, storage_manager
from server.service.permission import PermissionService
from server.util.tool import safe_int


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _allowed_camera_ids(user) -> set[int] | None:
    """Camera ids the user may view (None = all). Default-deny for non-superusers."""
    if PermissionService.is_superuser(user):
        return None
    scope = PermissionService._merged_scope(user, 'camera_scope')
    star = scope.get('*')
    if star and ('view' in star or '*' in star):
        return None
    allowed = set()
    for uuid, actions in scope.items():
        if uuid == '*':
            continue
        if 'view' in actions or '*' in actions:
            try:
                allowed.add(Camera.get_by_uuid(uuid).id)
            except RowNotFoundException:
                pass
    return allowed


class DetectionController:
    @classmethod
    def search(cls, user, args) -> dict:
        allowed = _allowed_camera_ids(user)
        requested = [int(c) for c in args.getlist('camera_id') if c.isdigit()] if hasattr(args, 'getlist') else []
        group = args.get('group') or 'clip'
        if allowed is not None:
            camera_ids = list(set(requested) & allowed) if requested else list(allowed)
            if not camera_ids:
                return {'count': 0, 'group': group, 'items': []}
        else:
            camera_ids = requested or None
        labels = (args.getlist('label') if hasattr(args, 'getlist') else None) or None
        zone_ids = [int(z) for z in args.getlist('zone_id') if z.isdigit()] if hasattr(args, 'getlist') else []
        return detection_search.search(
            camera_ids=camera_ids, labels=labels,
            start=_parse_ms(args.get('start')), end=_parse_ms(args.get('end')),
            zone_ids=zone_ids or None,
            min_confidence=safe_int(args.get('min_confidence'), None) if args.get('min_confidence') else None,
            group=group,
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))

    @classmethod
    def timeline(cls, user, camera_uuid: str, start, end, labels) -> dict:
        camera = cls._scoped_camera(user, camera_uuid)
        markers = detection_search.timeline_markers(camera.id, start, end, labels)
        coverage = playback_planner.build_timeline(camera.id, start, end)['ranges']
        return {'markers': markers, 'coverage': coverage}

    @classmethod
    def overlay(cls, user, camera_uuid: str, start, end, labels) -> dict:
        camera = cls._scoped_camera(user, camera_uuid)
        return detection_search.overlay_tracks(camera.id, start, end, labels)

    @classmethod
    def get(cls, user, detection_id: int) -> dict:
        det = cls._scoped_detection(user, detection_id)
        return det.to_dict()

    @classmethod
    def snapshot(cls, user, detection_id: int) -> bytes | None:
        det = cls._scoped_detection(user, detection_id)
        seg = Segment.get_at(det.camera_id, det.ts)
        if not seg:
            return None
        disk = Disk.get_by_id(seg.disk_id)
        if not disk:
            return None
        path = storage_manager.abs_path(disk, seg.rel_path)
        if not os.path.exists(path):
            return None
        offset = max(0.0, (det.ts - seg.start_ts).total_seconds())
        try:
            out = subprocess.run(ffmpeg.build_frame_cmd(path, offset), capture_output=True, timeout=15)
            return out.stdout if out.returncode == 0 and out.stdout else None
        except (subprocess.SubprocessError, OSError):
            return None

    # ── scope helpers ──────────────────────────────────────────────────────────
    @classmethod
    def _scoped_camera(cls, user, camera_uuid: str) -> Camera:
        camera = Camera.get_by_uuid(camera_uuid)
        if not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        return camera

    @classmethod
    def _scoped_detection(cls, user, detection_id: int) -> Detection:
        det = Detection.get_by_id(detection_id)
        if not det:
            raise RowNotFoundException()
        camera = Camera.get_by_id(det.camera_id)
        if not camera or not PermissionService.has_camera_scope(user, camera.uuid, 'view'):
            raise NoPermissionException('camera_scope_denied')
        return det
