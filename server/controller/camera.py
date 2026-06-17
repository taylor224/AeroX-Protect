import logging

from server.driver import factory
from server.driver.base import DriverAuthError, DriverError
from server.exception import ConflictException, InvalidParameterException, RowNotFoundException
from server.model import db
from server.model.audit_log import AuditLog
from server.model.camera import STATUS_ERROR, STATUS_ONLINE, STATUS_UNKNOWN, Camera
from server.model.stream import Stream, go2rtc_name_for
from server.service import capability_probe, go2rtc_sync
from server.driver.go2rtc import Go2rtcDriver

logger = logging.getLogger(__name__)

# go2rtc source strings are '#'-delimited (ffmpeg:URL#input=…#video=copy and the exec:
# scheme). A host/rtsp_path carrying '#', whitespace or control chars could inject extra
# go2rtc source directives, so reject them before they reach build_source().
_INJECT_CHARS = set('#\r\n\t ')


def _reject_injection(value: str, field: str):
    if value and (set(value) & _INJECT_CHARS or any(ord(ch) < 0x20 for ch in value)):
        raise InvalidParameterException('%s contains invalid characters' % field)


class CameraController:
    @classmethod
    def get_list(cls, page, items_per_page, q, sort, order) -> tuple[int, list[dict]]:
        total, rows = Camera.get_list(page, items_per_page, q, sort, order)
        return total, [c.to_dict(with_streams=True) for c in rows]

    @classmethod
    def get(cls, camera_uuid: str) -> dict:
        return Camera.get_by_uuid(camera_uuid).to_dict(with_streams=True, with_capabilities=True)

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        name = (data.get('name') or '').strip()
        host = (data.get('host') or '').strip()
        if not name or not host:
            raise InvalidParameterException('name and host are required')
        _reject_injection(host, 'host')

        serial = data.get('serial')
        channel = int(data.get('channel') or 1)
        if Camera.find_duplicate(serial, host, channel) is not None:
            raise ConflictException('camera already registered (serial or host+channel)')

        camera = Camera()
        camera.name = name
        camera.host = host
        camera.vendor = data.get('vendor') or 'unknown'
        camera.driver = data.get('driver') or 'onvif'
        camera.model = data.get('model')
        camera.firmware = data.get('firmware')
        camera.serial = serial
        camera.onvif_port = data.get('onvif_port')
        camera.http_port = data.get('http_port')
        camera.rtsp_port = data.get('rtsp_port') or 554
        _t = (data.get('rtsp_transport') or 'auto').lower()
        camera.rtsp_transport = _t if _t in ('tcp', 'udp') else None
        camera.use_https = bool(data.get('use_https'))
        camera.channel = channel
        camera.capabilities = data.get('capabilities')
        camera.ptz_supported = bool(data.get('ptz_supported'))
        camera.audio_supported = bool(data.get('audio_supported'))
        camera.two_way_audio = bool(data.get('two_way_audio'))
        if isinstance(data.get('ai_features'), dict):                 # per-camera AI enables at registration
            camera.ai_features = {k: bool(data['ai_features'].get(k))
                                  for k in ('audio', 'smoke', 'face', 'lpr') if k in data['ai_features']}
        camera.set_credentials(data.get('username'), data.get('password'))
        camera.created_by_id = actor.id
        camera.last_updated_by_id = actor.id
        db.session.add(camera)
        db.session.commit()

        cls._replace_streams(camera, data.get('streams') or _streams_from_caps(data.get('capabilities')))
        cls._sync_and_set_status(camera)

        AuditLog.record('camera_created', target=camera.uuid, user_id=actor.id,
                        detail={'name': name, 'vendor': camera.vendor})
        return camera.to_dict(with_streams=True)

    @classmethod
    def batch_create(cls, items: list[dict], common: dict, actor) -> dict:
        """M1 (PLAN P6 §5.5): add many cameras in one call. `common` (shared credentials/
        vendor/ports) is the base for every item; per-item fields override. Each create is
        independent — one failure doesn't abort the rest; per-item result is reported."""
        from server.service import feature_flag
        if not feature_flag.is_enabled('batch_camera_add'):
            raise InvalidParameterException('feature_disabled')
        if not isinstance(items, list) or not items:
            raise InvalidParameterException('items required')
        if len(items) > 100:
            raise InvalidParameterException('too many items (max 100)')

        common = common or {}
        results, created = [], 0
        for idx, item in enumerate(items):
            merged = {**common, **(item or {})}
            host = (merged.get('host') or '').strip()
            try:
                cam = cls.create(merged, actor)
                created += 1
                results.append({'index': idx, 'host': host, 'status': 'created',
                                'uuid': cam['uuid'], 'name': cam['name']})
            except (ConflictException, InvalidParameterException, DriverError, DriverAuthError) as e:
                db.session.rollback()
                results.append({'index': idx, 'host': host, 'status': 'failed', 'error': str(e)})
            except Exception as e:                       # never let one row break the batch
                db.session.rollback()
                logger.exception('batch camera create failed for %s', host)
                results.append({'index': idx, 'host': host, 'status': 'failed', 'error': str(e)})
        return {'created': created, 'failed': len(results) - created, 'results': results}

    @classmethod
    def update(cls, camera_uuid: str, data: dict, actor) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        if data.get('host') is not None:
            _reject_injection(str(data['host']).strip(), 'host')
        for field in ('name', 'host', 'model', 'firmware', 'vendor', 'driver'):
            if data.get(field) is not None:
                setattr(camera, field, data[field])
        for field in ('onvif_port', 'http_port', 'rtsp_port', 'channel'):
            if data.get(field) is not None:
                setattr(camera, field, data[field])
        if 'use_https' in data:
            camera.use_https = bool(data['use_https'])
        if 'rtsp_transport' in data:
            t = (data.get('rtsp_transport') or 'auto').lower()
            camera.rtsp_transport = t if t in ('tcp', 'udp') else None   # None = auto
        if 'is_enabled' in data:
            camera.is_enabled = bool(data['is_enabled'])
        if 'live_transcode' in data:                           # H.265 → H.264 live transcode
            camera.live_transcode = bool(data['live_transcode'])
        if 'fisheye' in data:                                  # P6 L5
            camera.fisheye = bool(data['fisheye'])
        if 'fisheye_params' in data:
            camera.fisheye_params = data['fisheye_params']
        if 'dual_recording' in data:                           # P6 R4
            camera.dual_recording = bool(data['dual_recording'])
        if 'dual_record_stream' in data:
            camera.dual_record_stream = data['dual_record_stream'] or None
        if 'ai_features' in data and isinstance(data['ai_features'], dict):
            merged = dict(camera.ai_features or {})
            for k in ('audio', 'smoke', 'face', 'lpr'):
                if k in data['ai_features']:
                    merged[k] = bool(data['ai_features'][k])
            camera.ai_features = merged
        if 'edge_recording' in data:                           # P6 R6
            camera.edge_recording = bool(data['edge_recording'])
        if 'edge_auto_import' in data:
            camera.edge_auto_import = bool(data['edge_auto_import'])
        # credentials only if provided (blank = keep existing)
        if data.get('username') or data.get('password'):
            camera.set_credentials(data.get('username'), data.get('password'))
        camera.last_updated_by_id = actor.id
        db.session.add(camera)
        db.session.commit()

        if data.get('streams') is not None:
            cls._replace_streams(camera, data['streams'])

        go2rtc_sync.remove_camera(camera)
        cls._sync_and_set_status(camera)
        AuditLog.record('camera_updated', target=camera.uuid, user_id=actor.id)
        from server.service import automation_events
        automation_events.emit('camera_config_changed', camera_id=camera.id)
        return camera.to_dict(with_streams=True)

    @classmethod
    def delete(cls, camera_uuid: str, actor):
        camera = Camera.get_by_uuid(camera_uuid)
        go2rtc_sync.remove_camera(camera)
        Stream.delete_for_camera(camera.id)
        camera.soft_delete(deleted_by_id=actor.id)
        from server.service import thumbnail_store
        thumbnail_store.remove(camera.uuid)
        AuditLog.record('camera_deleted', target=camera.uuid, user_id=actor.id)

    @classmethod
    def reprobe(cls, camera_uuid: str, actor) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        username, password = camera.get_credentials()
        try:
            result = capability_probe.probe(
                camera.host, http_port=camera.http_port or 80, onvif_port=camera.onvif_port or 80,
                rtsp_port=camera.rtsp_port or 554, username=username, password=password,
                use_https=camera.use_https, channel=camera.channel)
        except DriverAuthError:
            camera.set_status('unauthorized', 'reprobe unauthorized')
            return camera.to_dict(with_streams=True)
        except DriverError as e:
            camera.set_status(STATUS_ERROR, str(e))
            return camera.to_dict(with_streams=True)

        camera.model = result.get('model') or camera.model
        camera.firmware = result.get('firmware') or camera.firmware
        camera.capabilities = result.get('capabilities')
        camera.ptz_supported = bool(result.get('ptz_supported'))
        camera.audio_supported = bool(result.get('audio_supported'))
        camera.last_updated_by_id = actor.id
        db.session.add(camera)
        db.session.commit()
        if result.get('streams'):
            cls._replace_streams(camera, result['streams'])
            go2rtc_sync.remove_camera(camera)
            cls._sync_and_set_status(camera, mark_online=True)   # probe above proved reachability
        else:
            camera.set_status(STATUS_ONLINE)                     # probe succeeded, no stream change
        AuditLog.record('camera_reprobed', target=camera.uuid, user_id=actor.id)
        return camera.to_dict(with_streams=True, with_capabilities=True)

    @classmethod
    def health(cls, camera_uuid: str) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        driver = Go2rtcDriver()
        go2rtc = {s.go2rtc_name: driver.stream_status(s.go2rtc_name) for s in camera.streams}
        return {
            'status': camera.status,
            'last_seen_at': camera.to_dict()['last_seen_at'],
            'last_error': camera.last_error,
            'go2rtc': go2rtc,
        }

    @classmethod
    def streams(cls, camera_uuid: str) -> list[dict]:
        camera = Camera.get_by_uuid(camera_uuid)
        return [s.to_dict() for s in camera.streams]

    # ── helpers ────────────────────────────────────────────────────────────────
    @classmethod
    def _replace_streams(cls, camera: Camera, stream_dicts: list[dict]):
        Stream.delete_for_camera(camera.id)
        seen_roles = set()
        for sd in stream_dicts or []:
            role = (sd.get('role') or 'main').lower()
            if role in seen_roles:
                continue
            seen_roles.add(role)
            s = Stream()
            s.camera_id = camera.id
            s.role = role
            s.codec = sd.get('codec')
            s.width = sd.get('width')
            s.height = sd.get('height')
            s.fps = sd.get('fps')
            s.bitrate_kbps = sd.get('bitrate_kbps')
            s.audio_codec = sd.get('audio_codec')
            rtsp_path = sd.get('rtsp_path')
            _reject_injection(rtsp_path or '', 'rtsp_path')
            s.rtsp_path = rtsp_path
            s.rtsp_url_template = 'rtsp://{user}:{pass}@%s:%s%s' % (
                camera.host, camera.rtsp_port or 554, sd.get('rtsp_path') or '')
            s.go2rtc_name = go2rtc_name_for(camera.uuid, role)
            s.is_default_live = role == 'sub'
            s.is_default_full = role == 'main'
            db.session.add(s)
        db.session.commit()
        # ensure a default-live stream exists (fall back to main)
        streams = Stream.get_by_camera(camera.id)
        if streams and not any(s.is_default_live for s in streams):
            streams[0].is_default_live = True
            db.session.add(streams[0])
            db.session.commit()

    @classmethod
    def _sync_and_set_status(cls, camera: Camera, mark_online: bool = False):
        """Register the camera's streams in go2rtc. A successful sync only means go2rtc ACCEPTED
        the source config — it does NOT prove the camera is reachable — so we must not mark the
        camera online here (that would flip a genuinely-offline camera back to online on every
        edit). Online/offline is owned by the 30s frame-grab health check. `mark_online=True` is
        only for callers that just performed a real reachability probe (reprobe)."""
        try:
            result = go2rtc_sync.sync_camera(camera)
            failed = [name for name, r in result.items() if not r.get('ok')]
            if not result:
                camera.set_status(STATUS_UNKNOWN)
            elif failed:
                camera.set_status(STATUS_ERROR, 'go2rtc sync failed: %s' % ', '.join(failed))
            elif mark_online:
                camera.set_status(STATUS_ONLINE)
            # else: sync OK — leave status to the health check (don't fabricate "online")
        except Exception as e:  # never fail registration on sync glitch
            logger.warning('go2rtc sync error for %s: %s', camera.uuid, e)
            camera.set_status(STATUS_ERROR, str(e))


def _streams_from_caps(capabilities) -> list[dict]:
    if isinstance(capabilities, dict) and isinstance(capabilities.get('streams'), list):
        return capabilities['streams']
    return []
