"""Audio classification pipeline (PLAN P6 A4) — detector-node side.

Pulls the camera's shared go2rtc audio over RTSP through ffmpeg as mono 16 kHz s16le PCM,
slices it into fixed windows, classifies each window (PANNs if the model is in the image,
else the dependency-free energy stub), and yields report rows the node batches to
`POST /ai/ingest/audio`. The ffmpeg I/O is runtime-only; `pcm_to_floats` and
`classify_window` are pure and unit-tested.
"""
import logging
import struct
import subprocess
import time

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WINDOW_SECONDS = 1.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)
_MIN_REPORT_SCORE = 1          # drop pure-silence windows (score 0) to keep the table lean
_DROP_LABELS = {'ambient'}     # ambient/below-floor never reported


def build_ffmpeg_cmd(rtsp_url: str) -> list[str]:
    """ffmpeg → mono 16 kHz s16le PCM on stdout (no video)."""
    return [
        'ffmpeg', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-i', rtsp_url,
        '-vn', '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 's16le', '-',
    ]


def pcm_to_floats(raw: bytes) -> list[float]:
    """s16le little-endian PCM bytes → floats in [-1, 1]. Trailing odd byte ignored."""
    n = len(raw) // 2
    if n == 0:
        return []
    return [s / 32768.0 for s in struct.unpack('<%dh' % n, raw[:n * 2])]


def classify_window(samples: list[float], camera_id: int, ts_ms: int) -> list[dict]:
    """Classify one window → report rows (ready for POST). Empty if below the report floor."""
    from server.service import audio_classify
    rows = []
    for r in audio_classify.classify(samples, SAMPLE_RATE):
        if r['label'] in _DROP_LABELS or r['score'] < _MIN_REPORT_SCORE:
            continue
        rows.append({'camera_id': camera_id, 'ts': ts_ms, 'label': r['label'], 'score': r['score']})
    return rows


class AudioSource:
    """ffmpeg PCM reader. read_window() returns WINDOW_SAMPLES floats or None on EOF/error."""

    def __init__(self, rtsp_url: str):
        self.rtsp_url = rtsp_url
        self._proc: subprocess.Popen | None = None

    def open(self):
        self._proc = subprocess.Popen(
            build_ffmpeg_cmd(self.rtsp_url), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read_window(self) -> list[float] | None:
        if self._proc is None:
            self.open()
        assert self._proc and self._proc.stdout
        want = WINDOW_SAMPLES * 2
        buf = self._proc.stdout.read(want)
        if not buf or len(buf) < want:
            return None
        return pcm_to_floats(buf)

    def close(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None


def run_camera_audio(rtsp_url: str, camera_id: int, emit, stop=lambda: False):
    """Blocking loop: classify each window and hand report rows to `emit(rows)`. `stop()` →
    graceful exit. Re-opens the source on transient read failures (bounded backoff)."""
    src = AudioSource(rtsp_url)
    backoff = 1.0
    try:
        while not stop():
            samples = src.read_window()
            if samples is None:
                src.close()
                time.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 15.0)
                continue
            backoff = 1.0
            rows = classify_window(samples, camera_id, int(time.time() * 1000))
            if rows:
                emit(rows)
    finally:
        src.close()
