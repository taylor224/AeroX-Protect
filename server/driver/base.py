"""Camera driver abstraction (PLAN P1 §5.4, §7).

Vendor drivers (ISAPI/SUNAPI/ONVIF) implement a common interface so the rest of
the app is protocol-agnostic. PTZ/snapshot are optional — base raises NotSupported
so CompositeDriver can fall back to ONVIF.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests
from requests.auth import HTTPDigestAuth


# ── exceptions ───────────────────────────────────────────────────────────────
class DriverError(Exception):
    pass


class DriverUnreachable(DriverError):
    pass


class DriverAuthError(DriverError):
    """Credentials rejected (HTTP 401) — distinct from offline."""


class NotSupported(DriverError):
    pass


class PtzUnsupported(NotSupported):
    pass


# ── DTOs ─────────────────────────────────────────────────────────────────────
@dataclass
class DeviceInfo:
    vendor: str
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None


@dataclass
class StreamProfile:
    role: str                       # main / sub / third
    codec: str | None = None        # h264 / h265 / mjpeg
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate_kbps: int | None = None
    audio_codec: str | None = None
    rtsp_path: str | None = None
    token: str | None = None        # vendor profile token (onvif)

    def to_dict(self) -> dict:
        return {
            'role': self.role, 'codec': self.codec, 'width': self.width, 'height': self.height,
            'fps': self.fps, 'bitrate_kbps': self.bitrate_kbps, 'audio_codec': self.audio_codec,
            'rtsp_path': self.rtsp_path,
        }


@dataclass
class Capabilities:
    probe_source: str
    device: dict = field(default_factory=dict)
    ptz: dict = field(default_factory=lambda: {'supported': False})
    audio: dict = field(default_factory=lambda: {'input': False, 'output': False, 'two_way': False})
    events: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    streams: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'probe_source': self.probe_source,
            'device': self.device,
            'ptz': self.ptz,
            'audio': self.audio,
            'events': self.events,
            'snapshot': self.snapshot,
            'streams': [s.to_dict() if isinstance(s, StreamProfile) else s for s in self.streams],
        }


@dataclass
class Preset:
    token: str
    name: str


@dataclass
class HealthStatus:
    reachable: bool
    authenticated: bool
    status: str                     # online / offline / unauthorized / error
    detail: str | None = None


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


class CameraDriver(ABC):
    DEFAULT_TIMEOUT = 6

    def __init__(self, host, *, http_port=80, rtsp_port=554, onvif_port=80,
                 username=None, password=None, use_https=False, channel=1,
                 verify_tls=True, timeout=None):
        self.host = host
        self.http_port = http_port or 80
        self.rtsp_port = rtsp_port or 554
        self.onvif_port = onvif_port or 80
        self.username = username
        self.password = password
        self.use_https = use_https
        self.channel = channel or 1
        self.verify_tls = verify_tls
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    # --- HTTP helper (Digest) for vendor drivers ---
    @property
    def _scheme(self) -> str:
        return 'https' if self.use_https else 'http'

    def _base_url(self) -> str:
        return '%s://%s:%s' % (self._scheme, self.host, self.http_port)

    def _http_get(self, path: str, **kwargs) -> requests.Response:
        return self._http_request('GET', path, **kwargs)

    def _http_request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._base_url() + path
        try:
            resp = requests.request(
                method, url,
                auth=HTTPDigestAuth(self.username or '', self.password or ''),
                timeout=self.timeout, verify=self.verify_tls, **kwargs)
        except requests.exceptions.RequestException as e:
            raise DriverUnreachable(str(e))
        if resp.status_code == 401:
            raise DriverAuthError('unauthorized')
        return resp

    def rtsp_url(self, path: str) -> str:
        """RTSP URL WITH credentials — for go2rtc source injection only, never stored."""
        cred = ''
        if self.username:
            from urllib.parse import quote
            cred = '%s:%s@' % (quote(self.username, safe=''), quote(self.password or '', safe=''))
        return 'rtsp://%s%s:%s%s' % (cred, self.host, self.rtsp_port, path or '')

    # --- identification / probing (required) ---
    @abstractmethod
    def get_device_info(self) -> DeviceInfo: ...

    @abstractmethod
    def get_stream_profiles(self) -> list[StreamProfile]: ...

    @abstractmethod
    def get_capabilities(self) -> Capabilities: ...

    def healthcheck(self) -> HealthStatus:
        try:
            self.get_device_info()
            return HealthStatus(True, True, 'online')
        except DriverAuthError as e:
            return HealthStatus(True, False, 'unauthorized', str(e))
        except DriverUnreachable as e:
            return HealthStatus(False, False, 'offline', str(e))
        except DriverError as e:
            return HealthStatus(True, False, 'error', str(e))

    # --- media (optional) ---
    def get_snapshot(self) -> bytes | None:
        raise NotSupported('snapshot')

    # --- PTZ (optional; default unsupported) ---
    def ptz_continuous(self, pan, tilt, zoom, speed=None):
        raise PtzUnsupported('continuous')

    def ptz_stop(self):
        raise PtzUnsupported('stop')

    def ptz_relative(self, pan, tilt, zoom):
        raise PtzUnsupported('relative')

    def ptz_absolute(self, pan, tilt, zoom):
        raise PtzUnsupported('absolute')

    def ptz_list_presets(self) -> list[Preset]:
        raise PtzUnsupported('presets')

    def ptz_goto_preset(self, token, speed=None):
        raise PtzUnsupported('goto_preset')

    def ptz_set_preset(self, name, token=None) -> Preset:
        raise PtzUnsupported('set_preset')

    def ptz_remove_preset(self, token):
        raise PtzUnsupported('remove_preset')
