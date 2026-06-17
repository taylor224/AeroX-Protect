"""CompositeDriver — vendor driver primary, ONVIF fallback (PLAN P1 §5.4, §7.4).

Each call tries the vendor driver; on NotSupported it delegates to the ONVIF
fallback (e.g. older Hanwha firmware missing an attribute → ONVIF GetProfiles).
"""
from server.driver.base import (
    CameraDriver,
    Capabilities,
    DeviceInfo,
    HealthStatus,
    NotSupported,
    Preset,
    StreamProfile,
)


class CompositeDriver(CameraDriver):
    def __init__(self, primary: CameraDriver, fallback: CameraDriver | None = None):
        self.primary = primary
        self.fallback = fallback
        # mirror connection attrs from the primary for rtsp_url() etc.
        self.host = primary.host
        self.http_port = primary.http_port
        self.rtsp_port = primary.rtsp_port
        self.onvif_port = primary.onvif_port
        self.username = primary.username
        self.password = primary.password
        self.use_https = primary.use_https
        self.channel = primary.channel
        self.verify_tls = primary.verify_tls
        self.timeout = primary.timeout

    def _delegate(self, name: str, *args, **kwargs):
        try:
            return getattr(self.primary, name)(*args, **kwargs)
        except NotSupported:
            if self.fallback is not None:
                return getattr(self.fallback, name)(*args, **kwargs)
            raise

    def get_device_info(self) -> DeviceInfo:
        return self._delegate('get_device_info')

    def get_stream_profiles(self) -> list[StreamProfile]:
        return self._delegate('get_stream_profiles')

    def get_capabilities(self) -> Capabilities:
        return self._delegate('get_capabilities')

    def healthcheck(self) -> HealthStatus:
        return self.primary.healthcheck()

    def get_snapshot(self) -> bytes | None:
        return self._delegate('get_snapshot')

    def rtsp_url(self, path: str) -> str:
        return self.primary.rtsp_url(path)

    def ptz_continuous(self, pan, tilt, zoom, speed=None):
        return self._delegate('ptz_continuous', pan, tilt, zoom, speed)

    def ptz_stop(self):
        return self._delegate('ptz_stop')

    def ptz_relative(self, pan, tilt, zoom):
        return self._delegate('ptz_relative', pan, tilt, zoom)

    def ptz_absolute(self, pan, tilt, zoom):
        return self._delegate('ptz_absolute', pan, tilt, zoom)

    def ptz_list_presets(self) -> list[Preset]:
        return self._delegate('ptz_list_presets')

    def ptz_goto_preset(self, token, speed=None):
        return self._delegate('ptz_goto_preset', token, speed)

    def ptz_set_preset(self, name, token=None) -> Preset:
        return self._delegate('ptz_set_preset', name, token)

    def ptz_remove_preset(self, token):
        return self._delegate('ptz_remove_preset', token)
