"""Node agent (PLAN P4 §6.1, §7.2): join → heartbeat → poll assignments (etag/304) →
reconcile pipelines → batch-report detections. Pure `reconcile` is unit-tested; HTTP uses
httpx (lazy). Degrades to idle if no credentials are configured."""
import logging
import queue
import threading
import time
import uuid

from worker.detector import config
from worker.detector.backends import make_detector
from worker.detector.camera_pipeline import CameraPipeline

logger = logging.getLogger(__name__)


class NodeAgent:
    def __init__(self):
        self.session = uuid.uuid4().hex
        self.node_token = config.NODE_TOKEN
        self.node_id = None
        self.etag = None
        self.pipelines: dict[int, CameraPipeline] = {}
        self.report_q: queue.Queue = queue.Queue()
        self._running = False
        self._backend = None

    # ── pure reconcile (testable) ───────────────────────────────────────────────
    @staticmethod
    def reconcile(specs: list[dict], current: dict[int, dict]):
        """Given desired specs + running {camera_id: applied_spec}, return (start, stop,
        update). ANY spec difference (zones, confidence, labels, fps, epoch, …) re-specs —
        epoch alone only changes on node reassignment, so settings edits would otherwise
        never reach a running pipeline."""
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
            logger.warning('no JOIN_TOKEN/NODE_TOKEN — node idle (serving health only)')
            return False
        payload = {'name': config.NODE_NAME, 'gpu': config.GPU_ENABLED,
                   'capabilities': {'models': ['yolo11n', 'yolov8n'], 'backends': ['cuda' if config.GPU_ENABLED else 'cpu']},
                   'version': '4.0'}
        try:
            with self._client() as c:
                r = c.post('/ai/nodes/join', headers={'Authorization': 'Bearer ' + config.JOIN_TOKEN}, json=payload)
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
            with self._client() as c:
                r = c.post('/ai/nodes/heartbeat', headers=self._auth(),
                           json={'status': 'online', 'active_cameras': list(self.pipelines)})
            return (r.json() or {}).get('data') or {}
        except Exception:
            return {}

    def poll_assignments(self):
        try:
            headers = self._auth()
            if self.etag:
                headers['If-None-Match'] = self.etag
            with self._client() as c:
                r = c.get('/ai/nodes/assignments', headers=headers)
            if r.status_code == 304:
                return None
            data = (r.json() or {}).get('data') or {}
            self.etag = data.get('etag', self.etag)
            return data.get('items', [])
        except Exception:
            return None

    def flush_reports(self):
        batch = []
        while not self.report_q.empty() and len(batch) < 1000:
            batch.extend(self.report_q.get_nowait())
        if not batch:
            return
        epoch_map = {str(p.camera_id): p.epoch for p in self.pipelines.values()}
        try:
            with self._client() as c:
                c.post('/ai/ingest/detections', headers=self._auth(),
                       json={'node_id': self.node_id, 'batch': batch, 'epoch_map': epoch_map})
        except Exception:
            logger.exception('ingest post failed (%d dropped)', len(batch))

    # ── pipeline management ─────────────────────────────────────────────────────
    def _ensure_backend(self):
        if self._backend is None:
            self._backend = make_detector({'gpu_enabled': config.GPU_ENABLED, 'model': 'yolo11n',
                                           'force_backend': config.FORCE_BACKEND})
        return self._backend

    def apply_specs(self, specs: list[dict]):
        current = {cid: p.spec for cid, p in self.pipelines.items()}
        to_start, to_stop, to_update = self.reconcile(specs, current)
        for cid in to_stop:
            self.pipelines.pop(cid).stop()
            logger.info('stopped pipeline cam=%s', cid)
        for spec in to_update:
            # restart — source/tracker/sampler are bound at construction, so a live
            # pipeline can't safely mutate fps/sample-interval/rtsp in place
            self.pipelines.pop(spec['camera_id']).stop()
            p = CameraPipeline(spec, self._ensure_backend(), self.report_q, self.session)
            self.pipelines[spec['camera_id']] = p
            p.start()
            logger.info('restarted pipeline cam=%s (spec change)', spec['camera_id'])
        for spec in to_start:
            p = CameraPipeline(spec, self._ensure_backend(), self.report_q, self.session)
            self.pipelines[spec['camera_id']] = p
            p.start()
            logger.info('started pipeline cam=%s epoch=%s', spec['camera_id'], spec.get('epoch'))

    # ── supervisor loop ─────────────────────────────────────────────────────────
    def run(self):
        if not self.join():
            return
        self._running = True
        logger.info('node agent online (session=%s)', self.session[:8])
        last_hb = last_report = 0.0
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
            if now - last_report >= config.REPORT_INTERVAL_S:
                self.flush_reports()
                last_report = now
            time.sleep(0.5)

    def stop(self):
        self._running = False
        for p in list(self.pipelines.values()):
            p.stop()
