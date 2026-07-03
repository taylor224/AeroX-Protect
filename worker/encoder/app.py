"""AeroXProtect encoder node. FastAPI exposes /healthz (compose gate) + POST /transcode
(playback segment offload: raw segment bytes in → H.264 MPEG-TS bytes out); on startup it
spawns the NodeAgent supervisor (join → heartbeat → assignments → live encode sessions).
With no node credentials it degrades to a healthy idle node that still serves /transcode."""
import hmac
import ipaddress
import logging
import subprocess
import threading

from fastapi import FastAPI, Request, Response

from worker.encoder import config
from worker.encoder.node_agent import HW_ENCODERS, NodeAgent

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('axp-encoder')

app = FastAPI(title='axp-encoder', version='1.0.0')
_agent = NodeAgent()
# Playback bursts are bounded separately from live sessions so they can't oversubscribe CPU.
_transcode_slots = threading.Semaphore(max(2, config.MAX_SESSIONS * 2))

TRANSCODE_TIMEOUT_S = 45
BODY_MAX_BYTES = 128 * 1024 * 1024


def _safe_run():
    try:
        _agent.run()
    except Exception:
        logger.exception('node agent crashed')


@app.on_event('startup')
def _startup():
    threading.Thread(target=_safe_run, name='node-agent', daemon=True).start()


@app.on_event('shutdown')
def _shutdown():
    _agent.stop()


@app.get('/healthz')
def healthz():
    return {
        'status': 'success',
        'data': {
            'service': 'axp-encoder',
            'hwaccel': config.HWACCEL,
            'node_online': bool(_agent.node_token),
            'sessions': len(_agent.sessions),
            'max_sessions': config.MAX_SESSIONS,
        },
    }


def _authorized(request: Request) -> bool:
    """Shared-secret check for /transcode. With no secret configured, fall back to
    LAN-trust: only private/loopback callers are accepted."""
    secret = config.ENCODE_CALLBACK_SECRET
    if secret:
        return hmac.compare_digest(request.headers.get('x-encode-secret', ''), secret)
    try:
        ip = ipaddress.ip_address(request.client.host)
        return ip.is_private or ip.is_loopback
    except (TypeError, ValueError):
        return False


def _hls_cmd() -> list[str]:
    """Mirror of the server's build_hls_transcode_cmd, reading/writing pipes and using
    this node's hardware encoder when configured."""
    encoder = HW_ENCODERS.get(config.HWACCEL, 'libx264')
    cmd = [config.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-y',
           '-i', 'pipe:0', '-map', '0:v:0', '-map', '0:a?']
    if encoder == 'libx264':
        cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p']
    else:
        cmd += ['-c:v', encoder, '-b:v', '4M']
    cmd += ['-c:a', 'aac', '-f', 'mpegts', 'pipe:1']
    return cmd


@app.post('/transcode')
async def transcode(request: Request):
    if not _authorized(request):
        return Response(status_code=403)
    body = await request.body()
    if not body or len(body) > BODY_MAX_BYTES:
        return Response(status_code=400)
    if not _transcode_slots.acquire(blocking=False):
        return Response(status_code=503)   # saturated — the backend falls back to local
    try:
        r = subprocess.run(_hls_cmd(), input=body, capture_output=True, timeout=TRANSCODE_TIMEOUT_S)
        if r.returncode != 0 or not r.stdout:
            logger.warning('transcode failed rc=%s', r.returncode)
            return Response(status_code=500)
        return Response(content=r.stdout, media_type='video/mp2t')
    except (subprocess.SubprocessError, OSError):
        logger.exception('transcode error')
        return Response(status_code=500)
    finally:
        _transcode_slots.release()
