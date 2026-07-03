"""Encoder-node work orders (EncodeJobSpec). The node is driven entirely by the spec —
no camera config lives on it, and every encode parameter is server-authoritative (the
node re-validates against its own allow-list, never runs arbitrary args)."""
import config
from server.model.camera import Camera
from server.model.encode_assignment import EncodeAssignment

# Matches the local paths: go2rtc `#video=h264#audio=aac` (live) and
# ffmpeg.build_hls_transcode_cmd (playback).
ENCODE_PROFILE = {'v_codec': 'libx264', 'preset': 'veryfast', 'crf': 23, 'a_codec': 'aac'}


def default_live_stream(camera):
    """The camera's enabled default-live (grid) stream — the only stream ever transcoded."""
    return next((s for s in camera.streams
                 if getattr(s, 'is_default_live', False) and s.enabled), None)


def raw_name(stream) -> str:
    """Companion copy stream the encoder pulls (registered by go2rtc_sync)."""
    return '%s_raw' % stream.go2rtc_name


def enc_name(stream) -> str:
    """Stream name the encoder publishes H.264 into (created by the RTSP publish)."""
    return '%s_enc' % stream.go2rtc_name


def live_job_spec(camera_id: int) -> dict | None:
    """Server→node work order for one camera's live transcode. None if the camera has
    no default-live stream or no longer needs transcoding."""
    cam = Camera.get_by_id(camera_id)
    if not cam:
        return None
    stream = default_live_stream(cam)
    if stream is None:
        return None
    from server.service.go2rtc_sync import live_transcode_enabled
    if not live_transcode_enabled(cam, stream):
        return None
    a = EncodeAssignment.get_for_camera(camera_id)
    return {
        'camera_id': camera_id,
        'epoch': a.epoch if a else 0,
        'pull_url': '%s/%s' % (config.GO2RTC_RTSP, raw_name(stream)),
        'publish_url': '%s/%s' % (config.GO2RTC_RTSP, enc_name(stream)),
        **ENCODE_PROFILE,
    }
