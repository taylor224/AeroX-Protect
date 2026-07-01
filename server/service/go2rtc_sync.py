"""Sync camera streams into go2rtc (PLAN P1 §5.6).

go2rtc keeps ONE source connection per camera/stream; live (P1), recording (P2),
and AI (P4) all consume it. Credentials are decrypted at runtime and injected into
the go2rtc source only — the DB stores a placeholder template, never plaintext.
"""
import logging
from urllib.parse import quote

from server.driver.go2rtc import Go2rtcDriver, Go2rtcError

logger = logging.getLogger(__name__)


def live_transcode_enabled(camera, stream) -> bool:
    """Whether go2rtc must transcode this stream to H.264 for the browser.

    Only the default-live (grid) stream is ever transcoded — one shared on-demand producer
    fans out to all viewers. We transcode when the camera source is H.265/HEVC (MSE and
    WebRTC can't decode HEVC in Chrome/Firefox → live would fail), or when forced via the
    per-camera `live_transcode` flag. The main/archive stream always stays copy (recorded
    without re-encode)."""
    if not getattr(stream, 'is_default_live', False):
        return False
    return getattr(camera, 'live_transcode', False) or (getattr(stream, 'codec', None) == 'h265')


def build_source(camera, stream) -> str:
    """go2rtc source for a camera stream (copy = no re-encode).

    `camera.rtsp_transport` selects how go2rtc connects to the camera over RTSP:
      - auto (default/NULL) → go2rtc's native RTSP client (interleaved TCP)
      - tcp / udp           → forced via go2rtc's ffmpeg source (built-in rtsp/tcp|rtsp/udp preset)
    """
    username, password = camera.get_credentials()
    cred = ''
    if username:
        cred = '%s:%s@' % (quote(username, safe=''), quote(password or '', safe=''))
    rtsp_port = camera.rtsp_port or 554
    path = stream.rtsp_path or ''
    rtsp_url = 'rtsp://%s%s:%s%s' % (cred, camera.host, rtsp_port, path)

    transport = (getattr(camera, 'rtsp_transport', None) or 'auto').lower()
    input_pre = '#input=rtsp/%s' % transport if transport in ('tcp', 'udp') else ''

    # Live transcode (H.265 cams): browsers can't decode H.265 over WebRTC/MSE, so for the
    # default-live stream we transcode to H.264 via go2rtc's ffmpeg source. go2rtc runs ONE
    # such producer per stream and fans it out to every viewer — N watchers = 1 transcode,
    # and it's on-demand (no watchers → no ffmpeg). The main/archive stream stays copy.
    # Audio is transcoded to AAC too — a copied PCM/G.711 track can't play over MSE.
    if live_transcode_enabled(camera, stream):
        return 'ffmpeg:%s%s#video=h264#audio=aac' % (rtsp_url, input_pre)

    if input_pre:
        return 'ffmpeg:%s%s#video=copy#audio=copy' % (rtsp_url, input_pre)
    return '%s#video=copy#audio=copy' % rtsp_url


def sync_camera(camera, driver: Go2rtcDriver | None = None) -> dict:
    """Push all enabled streams of a camera to go2rtc. Returns per-stream result."""
    driver = driver or Go2rtcDriver()
    results = {}
    for stream in camera.streams:
        if not stream.enabled or not camera.is_enabled:
            continue
        try:
            driver.put_stream(stream.go2rtc_name, build_source(camera, stream))
            results[stream.go2rtc_name] = {'ok': True}
        except Go2rtcError as e:
            logger.warning('go2rtc sync failed for %s: %s', stream.go2rtc_name, e)
            results[stream.go2rtc_name] = {'ok': False, 'error': str(e)}
    return results


def remove_camera(camera, driver: Go2rtcDriver | None = None) -> None:
    """Remove a camera's streams from go2rtc (call before soft-deleting streams)."""
    driver = driver or Go2rtcDriver()
    for stream in camera.streams:
        try:
            driver.delete_stream(stream.go2rtc_name)
        except Go2rtcError as e:
            logger.warning('go2rtc remove failed for %s: %s', stream.go2rtc_name, e)
