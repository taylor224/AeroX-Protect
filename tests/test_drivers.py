import pytest

from server.driver import factory, isapi, sunapi
from server.driver.base import DeviceInfo, DriverAuthError, DriverError
from server.driver.composite import CompositeDriver
from server.driver.isapi import IsapiDriver
from server.driver.onvif import OnvifDriver

ISAPI_DEVICE = """<?xml version="1.0" encoding="UTF-8"?>
<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <model>DS-2CD2386G2</model>
  <serialNumber>DS-2CD2386G2-20240101</serialNumber>
  <firmwareVersion>V5.7.3</firmwareVersion>
  <deviceType>IPCamera</deviceType>
</DeviceInfo>"""

ISAPI_CHANNELS = """<StreamingChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <StreamingChannel><id>101</id><Video>
    <videoCodecType>H.265</videoCodecType>
    <videoResolutionWidth>3840</videoResolutionWidth>
    <videoResolutionHeight>2160</videoResolutionHeight>
    <maxFrameRate>2000</maxFrameRate></Video></StreamingChannel>
  <StreamingChannel><id>102</id><Video>
    <videoCodecType>H.264</videoCodecType>
    <videoResolutionWidth>704</videoResolutionWidth>
    <videoResolutionHeight>480</videoResolutionHeight>
    <maxFrameRate>1500</maxFrameRate></Video></StreamingChannel>
</StreamingChannelList>"""

ISAPI_PRESETS = """<PTZPresetList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <PTZPreset><id>1</id><presetName>Gate</presetName></PTZPreset>
  <PTZPreset><id>2</id><presetName>Yard</presetName></PTZPreset>
</PTZPresetList>"""

SUNAPI_DEVICE = "Model=XNP-6400R\nFirmwareVersion=2.21.06\nDeviceType=PTZ\nSerialNumber=ZN7R-001\n"

SUNAPI_PROFILES = (
    "Channel.0.Profile.1.Name=MAIN\nChannel.0.Profile.1.EncodingType=H265\n"
    "Channel.0.Profile.1.Resolution=2560x1440\nChannel.0.Profile.1.FrameRate=30\n"
    "Channel.0.Profile.2.EncodingType=H264\nChannel.0.Profile.2.Resolution=640x360\n"
    "Channel.0.Profile.2.FrameRate=15\n"
)

SUNAPI_PRESETS = "Preset.1.Name=Gate\nPreset.2.Name=Yard\n"


# ── ISAPI parsing ────────────────────────────────────────────────────────────
def test_isapi_device_info():
    d = isapi.parse_device_info(ISAPI_DEVICE)
    assert (d.vendor, d.model, d.firmware) == ('hikvision', 'DS-2CD2386G2', 'V5.7.3')
    assert d.serial == 'DS-2CD2386G2-20240101'


def test_isapi_channels():
    profiles = isapi.parse_channels(ISAPI_CHANNELS)
    assert [p.role for p in profiles] == ['main', 'sub']
    main, sub = profiles
    assert (main.codec, main.width, main.height, main.fps) == ('h265', 3840, 2160, 20)
    assert main.rtsp_path == '/Streaming/Channels/101'
    assert (sub.codec, sub.fps) == ('h264', 15)


def test_isapi_presets():
    presets = isapi.parse_presets(ISAPI_PRESETS)
    assert [(p.token, p.name) for p in presets] == [('1', 'Gate'), ('2', 'Yard')]


def test_isapi_ptz_mapping():
    drv = IsapiDriver('10.0.0.1', username='a', password='b')
    body = drv._ptz_continuous_body(0.5, -0.5, 0)
    assert body == '<PTZData><pan>50</pan><tilt>-50</tilt><zoom>0</zoom></PTZData>'
    # clamp out-of-range
    assert '<pan>100</pan>' in drv._ptz_continuous_body(2.0, 0, 0)


def test_rtsp_url_includes_credentials():
    drv = IsapiDriver('10.0.0.1', rtsp_port=554, username='admin', password='p@ss')
    url = drv.rtsp_url('/Streaming/Channels/101')
    assert url == 'rtsp://admin:p%40ss@10.0.0.1:554/Streaming/Channels/101'


# ── SUNAPI parsing ───────────────────────────────────────────────────────────
def test_sunapi_device_info():
    d = sunapi.parse_device_info(SUNAPI_DEVICE)
    assert (d.vendor, d.model, d.firmware, d.serial) == ('hanwha', 'XNP-6400R', '2.21.06', 'ZN7R-001')


def test_sunapi_profiles():
    profiles = sunapi.parse_video_profiles(SUNAPI_PROFILES)
    assert [p.role for p in profiles] == ['main', 'sub']
    main, sub = profiles
    assert (main.codec, main.width, main.height, main.fps) == ('h265', 2560, 1440, 30)
    assert main.rtsp_path == '/profile1/media.smp'
    assert sub.rtsp_path == '/profile2/media.smp'


def test_sunapi_presets():
    presets = sunapi.parse_presets(SUNAPI_PRESETS)
    assert [(p.token, p.name) for p in presets] == [('1', 'Gate'), ('2', 'Yard')]


# ── factory ──────────────────────────────────────────────────────────────────
def test_detect_vendor_hikvision(monkeypatch):
    monkeypatch.setattr(IsapiDriver, 'get_device_info', lambda self: DeviceInfo('hikvision'))
    assert factory.detect_vendor('10.0.0.1', username='a', password='b') == ('hikvision', 'isapi')


def test_detect_vendor_auth_still_identifies(monkeypatch):
    def boom(self):
        raise DriverAuthError('401')
    monkeypatch.setattr(IsapiDriver, 'get_device_info', boom)
    assert factory.detect_vendor('10.0.0.1') == ('hikvision', 'isapi')


def test_detect_vendor_unknown(monkeypatch):
    from server.driver.sunapi import SunapiDriver
    for cls in (IsapiDriver, SunapiDriver, OnvifDriver):
        monkeypatch.setattr(cls, 'get_device_info', lambda self: (_ for _ in ()).throw(DriverError('x')))
    assert factory.detect_vendor('10.0.0.1') == ('unknown', 'onvif')


def test_build_driver_wraps_with_onvif_fallback():
    drv = factory.build_driver('isapi', '10.0.0.1', username='a', password='b')
    assert isinstance(drv, CompositeDriver)
    assert isinstance(drv.primary, IsapiDriver)
    assert isinstance(drv.fallback, OnvifDriver)


def test_go2rtc_get_frame_rejects_non_jpeg(monkeypatch):
    """A cold/garbage frame.jpeg response (tiny or non-JPEG) must not be treated as a frame —
    caching it produced gray/broken thumbnails."""
    from server.driver import go2rtc as g

    class _R:
        def __init__(self, status, content):
            self.status_code, self.content = status, content

    drv = g.Go2rtcDriver()
    monkeypatch.setattr(g.requests, 'get', lambda *a, **k: _R(200, b'not-a-jpeg-16b!!'))
    assert drv.get_frame('cam_x') is None                       # 16-byte garbage → None
    monkeypatch.setattr(g.requests, 'get', lambda *a, **k: _R(200, b'\xff\xd8' + b'x' * 800))
    assert drv.get_frame('cam_x') is not None                   # real JPEG → bytes
    monkeypatch.setattr(g.requests, 'get', lambda *a, **k: _R(200, b'\xff\xd8tiny'))
    assert drv.get_frame('cam_x') is None                       # JPEG magic but too small → None


def test_go2rtc_get_frame_retries_past_keyframe(monkeypatch):
    """Cold on-demand/transcoded sources emit a small pre-keyframe frame first, then a real
    one once a keyframe lands. get_frame must keep retrying and return the real (larger) frame
    rather than caching the gray one."""
    from server.driver import go2rtc as g

    class _R:
        def __init__(self, status, content):
            self.status_code, self.content = status, content

    monkeypatch.setattr(g.time, 'sleep', lambda *_: None)
    seq = iter([b'\xff\xd8' + b'g' * 600,        # cold: small (gray) but valid JPEG
                b'\xff\xd8' + b'g' * 700,         # still small
                b'\xff\xd8' + b'P' * 9000])        # keyframe arrived: real picture
    monkeypatch.setattr(g.requests, 'get', lambda *a, **k: _R(200, next(seq)))
    drv = g.Go2rtcDriver()
    frame = drv.get_frame('cam_x', retries=3)
    assert frame is not None and len(frame) == 9002             # returned the real frame


def test_go2rtc_get_frame_width_param(monkeypatch):
    """`width` is passed to go2rtc as the `w=` scale param."""
    from server.driver import go2rtc as g
    captured = {}

    class _R:
        status_code = 200
        content = b'\xff\xd8' + b'x' * 9000

    def _get(url, params=None, timeout=None):
        captured['params'] = params
        return _R()

    monkeypatch.setattr(g.requests, 'get', _get)
    g.Go2rtcDriver().get_frame('cam_x', width=640)
    assert captured['params'] == {'src': 'cam_x', 'w': 640}


def test_go2rtc_get_frame_offline_no_retry(monkeypatch):
    """A transport error (camera unreachable) bails immediately — no retry storm on offline cams."""
    from server.driver import go2rtc as g
    calls = {'n': 0}

    def _boom(*a, **k):
        calls['n'] += 1
        raise g.requests.RequestException('timeout')

    monkeypatch.setattr(g.requests, 'get', _boom)
    assert g.Go2rtcDriver().get_frame('cam_x', retries=3) is None
    assert calls['n'] == 1                                       # bailed after the first failure


# ── onvif RTSP-port auto-detection (PLAN P1 §5.2) ─────────────────────────────
class _FakeRes:
    def __init__(self, w, h):
        self.Width, self.Height = w, h


class _FakeVec:
    def __init__(self, w, h):
        self.Encoding = 'H264'
        self.Resolution = _FakeRes(w, h)
        self.RateControl = type('R', (), {'FrameRateLimit': 25})()


class _FakeProfile:
    def __init__(self, token, w, h):
        self.token = token
        self.VideoEncoderConfiguration = _FakeVec(w, h)


class _FakeMedia:
    """Mimics the onvif media service: GetProfiles + GetStreamUri returning a non-default RTSP port."""
    def __init__(self, port):
        self._port = port

    def GetProfiles(self):
        return [_FakeProfile('main', 1920, 1080), _FakeProfile('sub', 640, 360)]

    def GetStreamUri(self, _req):
        uri = 'rtsp://10.0.0.5:%d/Streaming/Channels/101' % self._port
        return type('U', (), {'Uri': uri})()


def test_onvif_stream_profiles_detect_rtsp_port():
    drv = OnvifDriver('10.0.0.5', onvif_port=80, username='a', password='b')
    drv._camera = object()  # short-circuit _connect() so no real network call
    drv._media = _FakeMedia(10554)
    profiles = drv.get_stream_profiles()
    assert profiles[0].rtsp_path == '/Streaming/Channels/101'
    assert profiles[0].rtsp_port == 10554


def test_capability_probe_surfaces_detected_rtsp_port(monkeypatch):
    from server.driver.base import Capabilities, StreamProfile
    from server.service import capability_probe

    monkeypatch.setattr(capability_probe.factory, 'detect_vendor', lambda host, **kw: ('onvif', 'onvif'))

    class _Drv:
        def get_device_info(self):
            return DeviceInfo('onvif', model='Cam', firmware='1.0', serial='SN1')

        def get_capabilities(self):
            return Capabilities(probe_source='onvif',
                                streams=[StreamProfile(role='main', rtsp_path='/s1', rtsp_port=10554)])

    monkeypatch.setattr(capability_probe.factory, 'build_driver', lambda *a, **kw: _Drv())
    result = capability_probe.probe('10.0.0.5', username='a', password='b')
    assert result['detected_rtsp_port'] == 10554
