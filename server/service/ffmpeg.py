"""ffmpeg/ffprobe command builders + probe (PLAN P2 §6.3, §7.3, §7.4).

All commands are arg lists (shell=False) built from server-side values only — no
user input is ever interpolated into ffmpeg args (PLAN §13 security).
"""
import json
import subprocess

import config


def restream_url(go2rtc_name: str) -> str:
    return '%s/%s' % (config.GO2RTC_RTSP, go2rtc_name)


# P6 L7 — HW-accelerated decode for re-encode paths (export/timelapse). Mode from the global
# AI settings (shares the P4 GPU toggle policy); `none` = CPU. ffmpeg auto-falls back to CPU
# if the accelerator is unavailable when mode='auto'.
def global_hwaccel() -> str:
    try:
        from server.model.ai_settings import AiSettings
        g = AiSettings.get_global()
        return (g.hwaccel if g else 'none') or 'none'
    except Exception:
        return 'none'


def _hwaccel_prefix() -> list[str]:
    mode = global_hwaccel()
    return [] if mode in (None, '', 'none') else ['-hwaccel', mode]


# ── recording: rolling copy-codec segments ───────────────────────────────────
def build_segment_cmd(input_url: str, out_pattern: str, segment_seconds: int = 10,
                      container: str = 'mpegts', video_codec: str | None = None) -> list[str]:
    """Rolling segment recorder (stream copy). Input is the go2rtc RESTREAM, which already
    emits clean, normalized timestamps — so we must NOT rewrite them with
    `-use_wallclock_as_timestamps`/`+genpts` (that jitters copy-muxed PTS and produces
    choppy, hard-to-seek recordings). It stays a pure copy (no re-encode) rather than the
    wallclock-based preset a direct-camera pull would need. Boundaries come from `-segment_time` + the
    camera's own keyframes; `-segment_atclocktime` is deliberately dropped (with `-c copy`
    it only forces the *decision* point, splits still wait for a keyframe, and combined with
    rewritten PTS it produced erratic/empty segments)."""
    cmd = [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'warning',
        '-rtsp_transport', 'tcp', '-timeout', '10000000',  # rtsp socket I/O timeout (10s, µs)
        '-i', input_url,
        '-map', '0:v:0', '-map', '0:a?',
    ]
    if container == 'mpegts':
        # MPEG-TS is the native HLS segment container: no moov/faststart fragility, resilient
        # to a truncated tail (crash/restart), clean concat, and it carries H.264/H.265 as-is
        # (no hvc1 tagging needed). Audio → AAC so PCM/G.711 cameras still record.
        cmd += ['-c:v', 'copy', '-c:a', 'aac', '-segment_format', 'mpegts']
    else:
        # Fragmented MP4. MP4 can't carry PCM/G.711 audio (copying it fails the header and the
        # whole recording dies) → transcode audio to AAC (cheap); video stays passthrough.
        # HEVC in MP4 MUST be tagged `hvc1` or Safari/QuickTime/browsers show a black clip.
        cmd += ['-c:v', 'copy']
        if video_codec == 'h265':
            cmd += ['-tag:v', 'hvc1']
        cmd += ['-c:a', 'aac',
                '-segment_format', 'mp4',
                '-segment_format_options', 'movflags=+frag_keyframe+empty_moov+default_base_moof']
    cmd += ['-f', 'segment', '-segment_time', str(segment_seconds),
            '-reset_timestamps', '1', '-strftime', '1']
    cmd.append(out_pattern)
    return cmd


# ── playback: on-demand HLS segment (MPEG-TS) ─────────────────────────────────
# The recorded-playback player is hls.js over a VOD playlist whose media segments are all
# MPEG-TS. .ts segments are served straight from disk; anything else is normalized here.
def build_hls_remux_cmd(src_path: str, out_path: str) -> list[str]:
    """Remux a recorded segment to MPEG-TS (stream copy) — used for legacy fMP4 segments so
    they play in the same hls.js playlist. Cheap: demux/remux only, no re-encode."""
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error',
        '-i', src_path, '-map', '0:v:0', '-map', '0:a?',
        '-c', 'copy', '-f', 'mpegts', '-y', out_path,
    ]


def build_hls_transcode_cmd(src_path: str, out_path: str) -> list[str]:
    """Transcode a recorded segment to H.264/AAC MPEG-TS so H.265 recordings play in browsers
    that can't decode HEVC (Chrome/Firefox). Decode may use the configured hwaccel."""
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', *_hwaccel_prefix(),
        '-i', src_path, '-map', '0:v:0', '-map', '0:a?',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-f', 'mpegts', '-y', out_path,
    ]


def build_keepwarm_cmd(input_url: str) -> list[str]:
    """A throwaway consumer that just holds go2rtc's on-demand producer open. go2rtc runs ONE
    producer per stream and stops it when the last consumer leaves; for a transcoded live
    stream (H.265→H.264) that means every viewer cold-starts ffmpeg and waits for a keyframe
    (visible breakup). Keeping one consumer attached keeps the transcode running, so real
    viewers join a warm, keyframe-flowing stream. `-c copy` = demux only (no decode), discarded
    to the null muxer, so this costs almost nothing beyond the transcode it pins up."""
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'warning',
        '-rtsp_transport', 'tcp', '-timeout', '5000000',
        '-i', input_url,
        '-map', '0', '-c', 'copy', '-f', 'null', '-',
    ]


def segment_ext(container: str) -> str:
    return 'ts' if container == 'mpegts' else 'mp4'


# ── export: concat copy / transcode ──────────────────────────────────────────
def build_concat_copy_cmd(list_file: str, out_path: str, start_trim: float, end_trim: float) -> list[str]:
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', list_file,
        '-ss', '%.3f' % start_trim, '-to', '%.3f' % end_trim,
        '-c', 'copy', '-movflags', '+faststart', '-progress', 'pipe:1', '-y', out_path,
    ]


def build_transcode_cmd(list_file: str, out_path: str, start_trim: float, end_trim: float,
                        scale_height: int = 1080) -> list[str]:
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', *_hwaccel_prefix(),
        '-f', 'concat', '-safe', '0', '-i', list_file,
        '-ss', '%.3f' % start_trim, '-to', '%.3f' % end_trim,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-vf', 'scale=-2:%d' % scale_height,
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        '-progress', 'pipe:1', '-y', out_path,
    ]


# P6 R3 — burned-in watermark (drawtext, libfreetype). Watermark text is user input, so it
# is whitelisted to a safe charset before being single-quoted into the filtergraph (§13).
WATERMARK_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def safe_watermark_text(text: str | None) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9 _.,:\-가-힣]", '', text or '')[:100]
    return cleaned or 'AeroX Protect'


def build_watermark_transcode_cmd(list_file: str, out_path: str, start_trim: float, end_trim: float,
                                  scale_height: int, text: str | None) -> list[str]:
    safe = safe_watermark_text(text)
    vf = (
        "scale=-2:%d,drawtext=fontfile=%s:text='%s':fontcolor=white@0.92:fontsize=20:"
        "box=1:boxcolor=black@0.4:boxborderw=6:x=14:y=14:expansion=none"
        % (scale_height, WATERMARK_FONT, safe)
    )
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', *_hwaccel_prefix(),
        '-f', 'concat', '-safe', '0', '-i', list_file,
        '-ss', '%.3f' % start_trim, '-to', '%.3f' % end_trim,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-vf', vf,
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        '-progress', 'pipe:1', '-y', out_path,
    ]


def build_timelapse_cmd(list_file: str, out_path: str, speed_factor: int, fps: int = 30) -> list[str]:
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', *_hwaccel_prefix(),
        '-f', 'concat', '-safe', '0', '-i', list_file, '-an',
        '-vf', 'setpts=PTS/%d,fps=%d' % (max(1, speed_factor), fps),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-progress', 'pipe:1', '-y', out_path,
    ]


PRESET_HEIGHTS = {'h264_1080p': 1080, 'h264_720p': 720, 'h264_480p': 480}


def preset_height(preset: str | None) -> int:
    return PRESET_HEIGHTS.get(preset or '', 1080)


# ── frame / thumbnail ────────────────────────────────────────────────────────
def build_frame_cmd(segment_path: str, offset_seconds: float) -> list[str]:
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error',
        '-ss', '%.3f' % max(0.0, offset_seconds), '-i', segment_path,
        '-frames:v', '1', '-q:v', '3', '-f', 'mjpeg', 'pipe:1',
    ]


def build_thumbnail_cmd(segment_path: str, out_path: str, width: int = 320) -> list[str]:
    return [
        config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error',
        '-i', segment_path, '-frames:v', '1', '-q:v', '5',
        '-vf', 'scale=%d:-2' % width, '-y', out_path,
    ]


# ── probe ─────────────────────────────────────────────────────────────────────
def probe(path: str, timeout: int = 20) -> dict | None:
    """Run ffprobe → normalized {duration_ms, video_codec, width, height, has_audio}."""
    cmd = [config.FFPROBE_BIN, '-hide_banner', '-loglevel', 'error',
           '-show_format', '-show_streams', '-print_format', 'json', path]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout or '{}')
    except (subprocess.SubprocessError, ValueError, OSError):
        return None
    return parse_probe(data)


def parse_probe(data: dict) -> dict:
    streams = data.get('streams', [])
    fmt = data.get('format', {})
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    duration = fmt.get('duration') or (video or {}).get('duration')
    codec = (video or {}).get('codec_name')
    if codec in ('hevc', 'h265'):
        codec = 'h265'
    elif codec == 'h264':
        codec = 'h264'
    return {
        'duration_ms': int(float(duration) * 1000) if duration else 0,
        'video_codec': codec,
        'width': int(video['width']) if video and video.get('width') else None,
        'height': int(video['height']) if video and video.get('height') else None,
        'has_audio': has_audio,
    }
