"""AeroXProtect AI detector (PLAN P4). FastAPI exposes /healthz (compose gate) + /benchmark;
on startup it spawns the NodeAgent supervisor (join → heartbeat → assignments → pipelines →
report). With no node credentials or no ultralytics, it degrades to a healthy idle node.
Global GPU authority is the server's ai_settings.gpu_enabled; GPU_ENABLED here is the
bootstrap hint passed into the inference backend."""
import logging
import threading

from fastapi import FastAPI

from worker.detector import config
from worker.detector.node_agent import NodeAgent

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('axp-detector')

app = FastAPI(title='axp-detector', version='4.0.0')
_agent = NodeAgent()


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
            'service': 'axp-detector',
            'gpu_enabled': config.GPU_ENABLED,
            'node_online': bool(_agent.node_token),
            'pipelines': len(_agent.pipelines),
            'backend': getattr(_agent._backend, 'name', None),
            'device': getattr(_agent._backend, 'device', None),
        },
    }


@app.get('/benchmark')
def benchmark():
    backend = _agent._ensure_backend()
    return {'status': 'success', 'data': {'backend': backend.name, 'device': backend.device}}
