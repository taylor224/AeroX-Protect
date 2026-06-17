"""Hikvision ISAPI driver (PLAN P1 §7.2). HTTP Digest + XML."""
import xml.etree.ElementTree as ET

from server.driver.base import (
    CameraDriver,
    Capabilities,
    DeviceInfo,
    DriverError,
    NotSupported,
    Preset,
    StreamProfile,
    clamp,
)


def _localname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _find(elem, name):
    """First descendant whose local tag == name (namespace-insensitive)."""
    for child in elem.iter():
        if _localname(child.tag) == name:
            return child
    return None


def _text(elem, name, default=None):
    node = _find(elem, name)
    return node.text.strip() if node is not None and node.text else default


def parse_device_info(xml_text: str) -> DeviceInfo:
    root = ET.fromstring(xml_text)
    return DeviceInfo(
        vendor='hikvision',
        model=_text(root, 'model'),
        firmware=_text(root, 'firmwareVersion'),
        serial=_text(root, 'serialNumber'),
    )


def _role_for_channel_id(channel_id: int) -> str:
    last = channel_id % 100
    return {1: 'main', 2: 'sub', 3: 'third'}.get(last, 'main')


def parse_channels(xml_text: str) -> list[StreamProfile]:
    root = ET.fromstring(xml_text)
    profiles: list[StreamProfile] = []
    for ch in root.iter():
        if _localname(ch.tag) != 'StreamingChannel':
            continue
        cid = _text(ch, 'id')
        if not cid:
            continue
        try:
            channel_id = int(cid)
        except ValueError:
            continue
        codec = (_text(ch, 'videoCodecType') or '').lower().replace('.', '').replace('+', '') or None
        if codec:
            codec = 'h265' if '265' in codec else ('h264' if '264' in codec else codec)
        width = _text(ch, 'videoResolutionWidth')
        height = _text(ch, 'videoResolutionHeight')
        max_fr = _text(ch, 'maxFrameRate')
        fps = int(int(max_fr) / 100) if max_fr and max_fr.isdigit() else None
        profiles.append(StreamProfile(
            role=_role_for_channel_id(channel_id),
            codec=codec,
            width=int(width) if width and width.isdigit() else None,
            height=int(height) if height and height.isdigit() else None,
            fps=fps,
            rtsp_path='/Streaming/Channels/%s' % channel_id,
        ))
    # de-dupe by role keeping first (main/sub/third)
    seen, unique = set(), []
    for p in profiles:
        if p.role in seen:
            continue
        seen.add(p.role)
        unique.append(p)
    return unique


class IsapiDriver(CameraDriver):
    @property
    def _ch(self) -> int:
        return self.channel

    def _main_channel_id(self) -> int:
        return self.channel * 100 + 1

    def get_device_info(self) -> DeviceInfo:
        resp = self._http_get('/ISAPI/System/deviceInfo')
        if resp.status_code != 200:
            raise DriverError('deviceInfo http %s' % resp.status_code)
        return parse_device_info(resp.text)

    def get_stream_profiles(self) -> list[StreamProfile]:
        resp = self._http_get('/ISAPI/Streaming/channels')
        if resp.status_code != 200:
            raise DriverError('channels http %s' % resp.status_code)
        return parse_channels(resp.text)

    def get_capabilities(self) -> Capabilities:
        info = self.get_device_info()
        profiles = self.get_stream_profiles()
        ptz = {'supported': False}
        try:
            r = self._http_get('/ISAPI/PTZCtrl/channels/%d/capabilities' % self._ch)
            if r.status_code == 200:
                ptz = {'supported': True, 'continuous': True, 'absolute': True, 'presets': True}
        except DriverError:
            pass
        events = {}
        try:
            r = self._http_get('/ISAPI/Event/triggers')
            if r.status_code == 200:
                text = r.text.lower()
                events = {
                    'motion': 'motiondetection' in text,
                    'linecross': 'linedetection' in text,
                    'intrusion': 'fielddetection' in text,
                    'tamper': 'tamperdetection' in text,
                    'transport': 'isapi_alertstream',
                }
        except DriverError:
            pass
        return Capabilities(
            probe_source='isapi',
            device={'vendor': 'hikvision', 'model': info.model, 'firmware': info.firmware, 'serial': info.serial},
            ptz=ptz,
            audio={'input': False, 'output': False, 'two_way': False},
            events=events,
            snapshot={'url': '/ISAPI/Streaming/channels/%d/picture' % self._main_channel_id()},
            streams=profiles,
        )

    def get_snapshot(self) -> bytes | None:
        resp = self._http_get('/ISAPI/Streaming/channels/%d/picture' % self._main_channel_id())
        return resp.content if resp.status_code == 200 else None

    # --- PTZ: backend [-1,1] -> ISAPI [-100,100] ---
    def _ptz_continuous_body(self, pan, tilt, zoom):
        return (
            '<PTZData><pan>%d</pan><tilt>%d</tilt><zoom>%d</zoom></PTZData>'
            % (round(clamp(pan) * 100), round(clamp(tilt) * 100), round(clamp(zoom) * 100))
        )

    def ptz_continuous(self, pan, tilt, zoom, speed=None):
        body = self._ptz_continuous_body(pan, tilt, zoom)
        self._http_request('PUT', '/ISAPI/PTZCtrl/channels/%d/continuous' % self._ch,
                           data=body, headers={'Content-Type': 'application/xml'})

    def ptz_stop(self):
        self.ptz_continuous(0, 0, 0)

    def ptz_list_presets(self) -> list[Preset]:
        resp = self._http_get('/ISAPI/PTZCtrl/channels/%d/presets' % self._ch)
        if resp.status_code != 200:
            return []
        return parse_presets(resp.text)

    def ptz_goto_preset(self, token, speed=None):
        self._http_request('PUT', '/ISAPI/PTZCtrl/channels/%d/presets/%s/goto' % (self._ch, token))

    def ptz_set_preset(self, name, token=None) -> Preset:
        if token is None:
            raise NotSupported('isapi preset requires id')
        body = '<PTZPreset><id>%s</id><presetName>%s</presetName></PTZPreset>' % (token, name)
        self._http_request('PUT', '/ISAPI/PTZCtrl/channels/%d/presets/%s' % (self._ch, token),
                           data=body, headers={'Content-Type': 'application/xml'})
        return Preset(token=str(token), name=name)

    def ptz_remove_preset(self, token):
        self._http_request('DELETE', '/ISAPI/PTZCtrl/channels/%d/presets/%s' % (self._ch, token))


def parse_presets(xml_text: str) -> list[Preset]:
    root = ET.fromstring(xml_text)
    presets = []
    for p in root.iter():
        if _localname(p.tag) != 'PTZPreset':
            continue
        pid = _text(p, 'id')
        name = _text(p, 'presetName') or _text(p, 'name') or ('Preset %s' % pid)
        if pid:
            presets.append(Preset(token=str(pid), name=name))
    return presets
