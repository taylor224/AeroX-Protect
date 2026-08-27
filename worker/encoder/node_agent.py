"""Encoder node agent: join → heartbeat → poll assignments (etag/304) → reconcile ffmpeg
publish sessions. Pure `reconcile` and `build_live_cmd` are unit-tested; HTTP uses httpx
(lazy). Degrades to a healthy idle node if no credentials are configured.

A session pulls the raw H.265 stream from central go2rtc and publishes the H.264
rendition back over RTSP. Heartbeats report only sessions that stayed up MIN_HEALTHY_S —
the server flips the viewer-facing source to the published stream only after that report,
so a failing publish never blacks out live (the local transcode keeps serving)."""
import logging
import subprocess
import time

from worker.encoder import config
from worker.procutil import graceful_stop, spawn

logger = logging.getLogger(__name__)

BACKOFF_START = 1.0
BACKOFF_MAX = 15.0
MIN_HEALTHY_S = 3.0       # a session must survive this long before being reported active
STABLE_RESET_S = 30.0     # …and this long before its crash backoff resets

ALLOWED_PRESETS = {'ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium'}
HW_ENCODERS = {'none': 'libx264', 'nvenc': 'h264_nvenc', 'qsv': 'h264_qsv',
               'vaapi': 'h264_vaapi', 'videotoolbox': 'h264_videotoolbox'}


def build_live_cmd(spec: dict) -> list[str] | None:
    """ffmpeg argv for one live encode session. Every server-provided value is validated
    against an allow-list — a spec can never smuggle arbitrary args (argv, shell=False)."""
    pull, publish = spec.get('pull_url') or '', spec.get('publish_url') or ''
    if not (pull.startswith('rtsp://') and publish.startswith('rtsp://')):
        return None
    if spec.get('v_codec') not in ('libx264', 'h264'):
        return None
    preset = spec.get('preset') or 'veryfast'
    if preset not in ALLOWED_PRESETS:
        return None
    try:
        crf = min(51, max(0, int(spec.get('crf', 23))))
    except (TypeError, ValueError):
        return None
    encoder = HW_ENCODERS.get(config.HWACCEL, 'libx264')
    cmd = [config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'warning',
           '-rtsp_transport', 'tcp', '-i', pull,
           '-map', '0:v:0', '-map', '0:a?']
    if encoder == 'libx264':
        cmd += ['-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-pix_fmt', 'yuv420p']
    else:
        cmd += ['-c:v', encoder, '-b:v', '4M']
    cmd += ['-c:a', 'aac', '-f', 'rtsp', '-rtsp_transport', 'tcp', publish]
    return cmd


class EncodeSession:
    """One camera's live encode process, self-supervising with exponential backoff
    (mirrors the recorder's Proc discipline)."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.popen: subprocess.Popen | None = None
        self.started_at = 0.0
        self.backoff = BACKOFF_START
        self.next_retry = 0.0
        self.restart_count = 0

    def _start(self):
        cmd = build_live_cmd(self.spec)
        if cmd is None:
            logger.warning('rejected encode spec cam=%s (validation failed)', self.spec.get('camera_id'))
            return
        try:
            self.popen = spawn(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.started_at = time.monotonic()
            logger.info('encode session started cam=%s pid=%s', self.spec.get('camera_id'), self.popen.pid)
        except OSError as e:
            logger.warning('encode spawn failed cam=%s: %s', self.spec.get('camera_id'), e)
            self.popen = None

    def tick(self):
        now = time.monotonic()
        if self.popen is not None and self.popen.poll() is None:
            if self.backoff != BACKOFF_START and now - self.started_at > STABLE_RESET_S:
                self.backoff = BACKOFF_START
            return
        if self.popen is not None:   # died — schedule a backoff respawn
            self.restart_count += 1
            self.next_retry = now + self.backoff
            self.backoff = min(self.backoff * 2, BACKOFF_MAX)
            self.popen = None
            logger.info('encode session died cam=%s restart=%d', self.spec.get('camera_id'), self.restart_count)
        if now >= self.next_retry:
            self._start()

    def healthy(self) -> bool:
        return (self.popen is not None and self.popen.poll() is None
                and time.monotonic() - self.started_at >= MIN_HEALTHY_S)

    def stop(self):
        p, self.popen = self.popen, None
        graceful_stop(p, timeout=5)
        logger.info('encode session stopped cam=%s', self.spec.get('camera_id'))


class NodeAgent:
    def __init__(self):
        self.node_token = config.NODE_TOKEN
        self.node_id = None
        self.etag = None
        self.sessions: dict[int, EncodeSession] = {}
        self._running = False

    # ── pure reconcile (testable) ───────────────────────────────────────────────
    @staticmethod
    def reconcile(specs: list[dict], current: dict[int, dict]):
        """Given desired specs + running {camera_id: applied_spec}, return (start, stop,
        update). ANY spec difference (urls, profile, epoch) re-specs the session."""
        want = {s['camera_id']: s for s in specs}
        to_start = [s for cid, s in want.items() if cid not in current]
        to_stop = [cid for cid in current if cid not in want]
        to_update = [s for cid, s in want.items() if cid in current and current[cid] != s]
        return to_start, to_stop, to_update

    # ── HTTP ────────────────────────────────────────────────────────────────────
    def _client(self):
        import httpx
        return httpx.Client(base_url=config.SERVER_API_URL, timeout=15)

    def join(self) -> bool:
        if self.node_token:
            return True                                   # pre-shared scoped token
        if not config.JOIN_TOKEN:
            logger.warning('no JOIN_TOKEN/NODE_TOKEN — encoder idle (serving health only)')
            return False
        payload = {'name': config.NODE_NAME, 'hwaccel': config.HWACCEL,
                   'max_sessions': config.MAX_SESSIONS, 'endpoint': config.ADVERTISE_URL,
                   'capabilities': {'hwaccels': [config.HWACCEL]}, 'version': '1.0'}
        try:
            with self._client() as c:
                r = c.post('/encode/nodes/join', headers={'Authorization': 'Bearer ' + config.JOIN_TOKEN},
                           json=payload)
            data = (r.json() or {}).get('data') or {}
            self.node_token = data.get('node_token')
            self.node_id = data.get('node_id')
            self.etag = data.get('assignments_etag')
            return bool(self.node_token)
        except Exception:
            logger.exception('join failed')
            return False

    def _auth(self):
        return {'Authorization': 'Bearer ' + self.node_token}

    def heartbeat(self):
        try:
            active = [cid for cid, s in self.sessions.items() if s.healthy()]
            payload = {'status': 'online', 'active_sessions': active}
            if config.ADVERTISE_URL:
                payload['endpoint'] = config.ADVERTISE_URL
            with self._client() as c:
                r = c.post('/encode/nodes/heartbeat', headers=self._auth(), json=payload)
            return (r.json() or {}).get('data') or {}
        except Exception:
            return {}

    def poll_assignments(self):
        try:
            headers = self._auth()
            if self.etag:
                headers['If-None-Match'] = self.etag
            with self._client() as c:
                r = c.get('/encode/nodes/assignments', headers=headers)
            if r.status_code == 304:
                return None
            data = (r.json() or {}).get('data') or {}
            self.etag = data.get('etag', self.etag)
            return data.get('items', [])
        except Exception:
            return None

    # ── session management ──────────────────────────────────────────────────────
    def apply_specs(self, specs: list[dict]):
        current = {cid: s.spec for cid, s in self.sessions.items()}
        to_start, to_stop, to_update = self.reconcile(specs, current)
        for cid in to_stop:
            self.sessions.pop(cid).stop()
        for spec in to_update:
            self.sessions.pop(spec['camera_id']).stop()
            self.sessions[spec['camera_id']] = EncodeSession(spec)
            logger.info('restarted session cam=%s (spec change)', spec['camera_id'])
        for spec in to_start:
            self.sessions[spec['camera_id']] = EncodeSession(spec)
            logger.info('starting session cam=%s epoch=%s', spec['camera_id'], spec.get('epoch'))

    # ── supervisor loop ─────────────────────────────────────────────────────────
    def run(self):
        if not self.join():
            return
        self._running = True
        logger.info('encoder node agent online')
        last_hb = 0.0
        while self._running:
            now = time.monotonic()
            if now - last_hb >= config.HEARTBEAT_INTERVAL_S:
                hb = self.heartbeat()
                last_hb = now
                if hb.get('assignments_etag') and hb['assignments_etag'] != self.etag:
                    self.etag = None                      # force re-fetch
            specs = self.poll_assignments()
            if specs is not None:
                self.apply_specs(specs)
            for s in list(self.sessions.values()):
                s.tick()
            time.sleep(0.5)

    def stop(self):
        self._running = False
        for s in list(self.sessions.values()):
            s.stop()
