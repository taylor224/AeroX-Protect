from server.driver import factory
from server.driver.base import DriverError, PtzUnsupported
from server.exception import InvalidParameterException
from server.model.camera import Camera
from server.model.ptz_preset import PtzPreset
from server.util.tool import safe_float


def _driver_for(camera: Camera):
    username, password = camera.get_credentials()
    return factory.build_driver(
        camera.driver, camera.host,
        http_port=camera.http_port or 80, onvif_port=camera.onvif_port or 80,
        rtsp_port=camera.rtsp_port or 554, username=username, password=password,
        use_https=camera.use_https, channel=camera.channel)


def _axis(data, key) -> float:
    v = safe_float(data.get(key), 0.0)
    if v < -1.0 or v > 1.0:
        raise InvalidParameterException('%s must be in [-1, 1]' % key)
    return v


class PtzController:
    @classmethod
    def execute(cls, camera_uuid: str, data: dict) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        if not camera.ptz_supported:
            raise InvalidParameterException('camera does not support PTZ')
        driver = _driver_for(camera)
        action = data.get('action')
        try:
            if action == 'continuous':
                speed = safe_float(data.get('speed'), None) if data.get('speed') is not None else None
                driver.ptz_continuous(_axis(data, 'pan'), _axis(data, 'tilt'), _axis(data, 'zoom'), speed)
            elif action == 'stop':
                driver.ptz_stop()
            elif action == 'relative':
                driver.ptz_relative(_axis(data, 'pan'), _axis(data, 'tilt'), _axis(data, 'zoom'))
            elif action == 'absolute':
                driver.ptz_absolute(_axis(data, 'pan'), _axis(data, 'tilt'), _axis(data, 'zoom'))
            elif action == 'goto_preset':
                token = data.get('token')
                if not token:
                    raise InvalidParameterException('token required')
                driver.ptz_goto_preset(token, safe_float(data.get('speed'), None))
            else:
                raise InvalidParameterException('unknown ptz action: %s' % action)
        except PtzUnsupported as e:
            raise InvalidParameterException('ptz action unsupported: %s' % e)
        except DriverError as e:
            raise InvalidParameterException('ptz failed: %s' % e)
        return {'action': action, 'ok': True}

    @classmethod
    def list_presets(cls, camera_uuid: str) -> list[dict]:
        camera = Camera.get_by_uuid(camera_uuid)
        cache = {p.ptz_token: p.name for p in PtzPreset.get_by_camera(camera.id)}
        try:
            presets = _driver_for(camera).ptz_list_presets()
        except (PtzUnsupported, DriverError):
            presets = []
        out = [{'token': p.token, 'name': cache.get(p.token, p.name)} for p in presets]
        if not out and cache:  # camera unreachable — show cached labels
            out = [{'token': t, 'name': n} for t, n in cache.items()]
        return out

    @classmethod
    def save_preset(cls, camera_uuid: str, data: dict) -> dict:
        camera = Camera.get_by_uuid(camera_uuid)
        name = (data.get('name') or '').strip()
        if not name:
            raise InvalidParameterException('name required')
        try:
            preset = _driver_for(camera).ptz_set_preset(name, data.get('token'))
        except (PtzUnsupported, DriverError) as e:
            raise InvalidParameterException('save preset failed: %s' % e)
        PtzPreset.upsert(camera.id, preset.token, name)
        return {'token': preset.token, 'name': name}

    @classmethod
    def remove_preset(cls, camera_uuid: str, token: str):
        camera = Camera.get_by_uuid(camera_uuid)
        try:
            _driver_for(camera).ptz_remove_preset(token)
        except (PtzUnsupported, DriverError) as e:
            raise InvalidParameterException('remove preset failed: %s' % e)
        PtzPreset.remove(camera.id, token)
