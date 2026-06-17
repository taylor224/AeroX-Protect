"""ONVIF driver (PLAN P1 §7.1) via onvif-zeep. Generic fallback for all vendors.

No camera hardware is available in CI, so this is structured defensively (best-effort
parsing, exceptions mapped to DriverError types) and exercised via mocked services.
"""
from urllib.parse import urlparse

from server.driver.base import (
    CameraDriver,
    Capabilities,
    DeviceInfo,
    DriverAuthError,
    DriverError,
    DriverUnreachable,
    Preset,
    StreamProfile,
    clamp,
)


def _norm_codec(encoding: str | None) -> str | None:
    if not encoding:
        return None
    e = str(encoding).lower()
    if '265' in e or 'hevc' in e:
        return 'h265'
    if '264' in e:
        return 'h264'
    if 'jpeg' in e:
        return 'mjpeg'
    return e


class OnvifDriver(CameraDriver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._camera = None
        self._media = None
        self._ptz = None
        self._profiles_cache = None

    def _connect(self):
        if self._camera is not None:
            return self._camera
        try:
            from onvif import ONVIFCamera
        except ImportError as e:  # pragma: no cover
            raise DriverError('onvif-zeep not installed: %s' % e)
        try:
            self._camera = ONVIFCamera(
                self.host, self.onvif_port, self.username or '', self.password or '')
            self._media = self._camera.create_media_service()
            return self._camera
        except Exception as e:  # zeep/connection/auth
            raise _map_onvif_error(e)

    def get_device_info(self) -> DeviceInfo:
        cam = self._connect()
        try:
            dm = cam.create_devicemgmt_service()
            info = dm.GetDeviceInformation()
        except Exception as e:
            raise _map_onvif_error(e)
        return DeviceInfo(
            vendor=_vendor_from_manufacturer(getattr(info, 'Manufacturer', None)),
            model=getattr(info, 'Model', None),
            firmware=getattr(info, 'FirmwareVersion', None),
            serial=getattr(info, 'SerialNumber', None),
        )

    def _get_profiles(self):
        if self._profiles_cache is None:
            self._connect()
            try:
                self._profiles_cache = self._media.GetProfiles()
            except Exception as e:
                raise _map_onvif_error(e)
        return self._profiles_cache

    def get_stream_profiles(self) -> list[StreamProfile]:
        profiles = self._get_profiles()
        parsed = []
        for p in profiles:
            vec = getattr(p, 'VideoEncoderConfiguration', None)
            width = height = fps = codec = None
            if vec is not None:
                codec = _norm_codec(getattr(vec, 'Encoding', None))
                res = getattr(vec, 'Resolution', None)
                if res is not None:
                    width, height = getattr(res, 'Width', None), getattr(res, 'Height', None)
                rate = getattr(vec, 'RateControl', None)
                if rate is not None:
                    fps = getattr(rate, 'FrameRateLimit', None)
            rtsp_path = None
            try:
                uri = self._media.GetStreamUri(
                    {'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
                     'ProfileToken': p.token})
                rtsp_path = urlparse(getattr(uri, 'Uri', '') or '').path or None
            except Exception:
                pass
            parsed.append(StreamProfile(
                role='main', codec=codec,
                width=int(width) if width else None, height=int(height) if height else None,
                fps=int(fps) if fps else None, rtsp_path=rtsp_path, token=p.token))
        # assign roles by descending resolution: largest=main, then sub/third
        parsed.sort(key=lambda s: (s.width or 0) * (s.height or 0), reverse=True)
        for i, s in enumerate(parsed):
            s.role = {0: 'main', 1: 'sub', 2: 'third'}.get(i, 'third')
        return parsed

    def get_capabilities(self) -> Capabilities:
        info = self.get_device_info()
        profiles = self.get_stream_profiles()
        ptz_supported = False
        try:
            cam = self._connect()
            caps = cam.create_devicemgmt_service().GetCapabilities({'Category': 'All'})
            ptz_supported = getattr(caps, 'PTZ', None) is not None
        except Exception:
            pass
        return Capabilities(
            probe_source='onvif',
            device={'vendor': info.vendor, 'model': info.model, 'firmware': info.firmware, 'serial': info.serial},
            ptz={'supported': ptz_supported, 'continuous': ptz_supported, 'presets': ptz_supported},
            audio={'input': False, 'output': False, 'two_way': False},
            events={'transport': 'onvif_pullpoint'},
            snapshot={},
            streams=profiles,
        )

    def _main_token(self):
        profiles = self._get_profiles()
        return profiles[0].token if profiles else None

    def _ptz_service(self):
        if self._ptz is None:
            self._ptz = self._connect().create_ptz_service()
        return self._ptz

    def ptz_continuous(self, pan, tilt, zoom, speed=None):
        token = self._main_token()
        self._ptz_service().ContinuousMove(
            {'ProfileToken': token,
             'Velocity': {'PanTilt': {'x': clamp(pan), 'y': clamp(tilt)}, 'Zoom': {'x': clamp(zoom)}}})

    def ptz_stop(self):
        self._ptz_service().Stop({'ProfileToken': self._main_token(), 'PanTilt': True, 'Zoom': True})

    def ptz_absolute(self, pan, tilt, zoom):
        self._ptz_service().AbsoluteMove(
            {'ProfileToken': self._main_token(),
             'Position': {'PanTilt': {'x': clamp(pan), 'y': clamp(tilt)}, 'Zoom': {'x': clamp(zoom)}}})

    def ptz_list_presets(self) -> list[Preset]:
        presets = self._ptz_service().GetPresets({'ProfileToken': self._main_token()})
        out = []
        for p in presets or []:
            out.append(Preset(token=str(getattr(p, 'token', '')), name=str(getattr(p, 'Name', '') or 'Preset')))
        return out

    def ptz_goto_preset(self, token, speed=None):
        self._ptz_service().GotoPreset({'ProfileToken': self._main_token(), 'PresetToken': token})

    def ptz_set_preset(self, name, token=None) -> Preset:
        res = self._ptz_service().SetPreset({'ProfileToken': self._main_token(), 'PresetName': name})
        return Preset(token=str(getattr(res, 'PresetToken', token or name)), name=name)

    def ptz_remove_preset(self, token):
        self._ptz_service().RemovePreset({'ProfileToken': self._main_token(), 'PresetToken': token})


def _vendor_from_manufacturer(manufacturer: str | None) -> str:
    if not manufacturer:
        return 'onvif'
    m = manufacturer.lower()
    if 'hikvision' in m:
        return 'hikvision'
    if 'hanwha' in m or 'samsung' in m or 'techwin' in m:
        return 'hanwha'
    return 'onvif'


def _map_onvif_error(e: Exception) -> DriverError:
    text = str(e).lower()
    if 'auth' in text or '401' in text or 'not authorized' in text or 'unauthorized' in text:
        return DriverAuthError(str(e))
    if 'timed out' in text or 'connection' in text or 'unreachable' in text or 'refused' in text:
        return DriverUnreachable(str(e))
    return DriverError(str(e))
