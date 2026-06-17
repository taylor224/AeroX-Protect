"""Hanwha SUNAPI driver (PLAN P1 §7.3). HTTP Digest + CGI (key=value / JSON)."""
import re

from server.driver.base import (
    CameraDriver,
    Capabilities,
    DeviceInfo,
    DriverError,
    Preset,
    StreamProfile,
    clamp,
)


def parse_kv(text: str) -> dict:
    """Parse SUNAPI key=value response into a flat dict."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or '=' not in line:
            continue
        key, _, value = line.partition('=')
        out[key.strip()] = value.strip()
    return out


def parse_device_info(text: str) -> DeviceInfo:
    kv = parse_kv(text)
    return DeviceInfo(
        vendor='hanwha',
        model=kv.get('Model') or kv.get('DeviceType'),
        firmware=kv.get('FirmwareVersion'),
        serial=kv.get('SerialNumber') or kv.get('ConnectedMACAddress'),
    )


def _codec_norm(value: str | None) -> str | None:
    if not value:
        return None
    v = value.lower()
    if '265' in v:
        return 'h265'
    if '264' in v:
        return 'h264'
    if 'mjpeg' in v or 'jpeg' in v:
        return 'mjpeg'
    return v


def parse_video_profiles(text: str) -> list[StreamProfile]:
    """Parse videoprofile key=value (Channel.0.Profile.<n>.<attr>=...)."""
    kv = parse_kv(text)
    profiles: dict[int, dict] = {}
    pat = re.compile(r'Channel\.\d+\.Profile\.(\d+)\.(\w+)')
    for key, value in kv.items():
        m = pat.match(key)
        if not m:
            continue
        idx = int(m.group(1))
        profiles.setdefault(idx, {})[m.group(2)] = value

    result = []
    for idx in sorted(profiles):
        attrs = profiles[idx]
        width = height = None
        res = attrs.get('Resolution')
        if res and 'x' in res:
            try:
                width, height = (int(x) for x in res.lower().split('x', 1))
            except ValueError:
                pass
        fr = attrs.get('FrameRate')
        role = 'main' if idx == 1 else ('sub' if idx == 2 else 'third')
        result.append(StreamProfile(
            role=role,
            codec=_codec_norm(attrs.get('EncodingType')),
            width=width,
            height=height,
            fps=int(fr) if fr and fr.isdigit() else None,
            bitrate_kbps=int(attrs['Bitrate']) if attrs.get('Bitrate', '').isdigit() else None,
            rtsp_path='/profile%d/media.smp' % idx,
            token=str(idx),
        ))
    return result


def parse_presets(text: str) -> list[Preset]:
    """Parse preset view (Preset.<n>.Name=... or Presets.<n>...)."""
    kv = parse_kv(text)
    presets: dict[str, str] = {}
    pat = re.compile(r'Preset(?:s)?\.(\d+)\.Name')
    for key, value in kv.items():
        m = pat.match(key)
        if m:
            presets[m.group(1)] = value
    return [Preset(token=num, name=name) for num, name in sorted(presets.items(), key=lambda x: int(x[0]))]


class SunapiDriver(CameraDriver):
    def _cgi(self, group: str, file: str, **params) -> str:
        query = '&'.join('%s=%s' % (k, v) for k, v in params.items())
        return '/%s-cgi/%s.cgi?%s' % (group, file, query)

    def get_device_info(self) -> DeviceInfo:
        resp = self._http_get(self._cgi('stw', 'system', msubmenu='deviceinfo', action='view'))
        if resp.status_code != 200:
            raise DriverError('deviceinfo http %s' % resp.status_code)
        return parse_device_info(resp.text)

    def get_stream_profiles(self) -> list[StreamProfile]:
        resp = self._http_get(self._cgi('stw', 'media', msubmenu='videoprofile', action='view', Channel=0))
        if resp.status_code != 200:
            raise DriverError('videoprofile http %s' % resp.status_code)
        return parse_video_profiles(resp.text)

    def get_capabilities(self) -> Capabilities:
        info = self.get_device_info()
        profiles = self.get_stream_profiles()
        ptz = {'supported': False}
        try:
            r = self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='preset', action='view', Channel=0))
            if r.status_code == 200:
                ptz = {'supported': True, 'continuous': True, 'absolute': True, 'presets': True}
        except DriverError:
            pass
        return Capabilities(
            probe_source='sunapi',
            device={'vendor': 'hanwha', 'model': info.model, 'firmware': info.firmware, 'serial': info.serial},
            ptz=ptz,
            audio={'input': False, 'output': False, 'two_way': False},
            events={'transport': 'sunapi_eventstatus'},
            snapshot={'url': '/stw-cgi/video.cgi?msubmenu=snapshot&action=view&Profile=1'},
            streams=profiles,
        )

    def get_snapshot(self) -> bytes | None:
        resp = self._http_get(self._cgi('stw', 'video', msubmenu='snapshot', action='view', Profile=1))
        return resp.content if resp.status_code == 200 else None

    # --- PTZ: backend [-1,1] -> SUNAPI normalized speed ---
    def ptz_continuous(self, pan, tilt, zoom, speed=None):
        self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='continuous', action='control', Channel=0,
                                 Pan=round(clamp(pan), 2), Tilt=round(clamp(tilt), 2), Zoom=round(clamp(zoom), 2)))

    def ptz_stop(self):
        self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='stop', action='control', Channel=0,
                                 OperationType='All'))

    def ptz_list_presets(self) -> list[Preset]:
        resp = self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='preset', action='view', Channel=0))
        return parse_presets(resp.text) if resp.status_code == 200 else []

    def ptz_goto_preset(self, token, speed=None):
        self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='preset', action='control', Channel=0, Preset=token))

    def ptz_set_preset(self, name, token=None) -> Preset:
        params = {'msubmenu': 'preset', 'action': 'add', 'Channel': 0, 'Name': name}
        if token is not None:
            params['Preset'] = token
        self._http_get(self._cgi('stw', 'ptzcontrol', **params))
        return Preset(token=str(token) if token is not None else name, name=name)

    def ptz_remove_preset(self, token):
        self._http_get(self._cgi('stw', 'ptzcontrol', msubmenu='preset', action='remove', Channel=0, Preset=token))
