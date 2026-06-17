"""ultralytics YOLO backend, CUDA or CPU (PLAN P4 §5.4). All heavy imports (torch,
ultralytics, numpy) are lazy so the module imports without them; warmup() loads the model.
device = cuda:0 when gpu_enabled & torch.cuda.is_available(), else cpu (FP16 on GPU)."""
import logging
import threading
import time

from worker.detector.backends.base import Detection

logger = logging.getLogger(__name__)


class YoloDetector:
    name = 'yolo'

    def __init__(self, spec: dict):
        self._spec = spec
        self._model = None
        self._lock = threading.Lock()
        self._model_name = spec.get('model', 'yolo11n')
        self._device = self._resolve_device(bool(spec.get('gpu_enabled')))
        self._healthy = False

    @staticmethod
    def _resolve_device(gpu_enabled: bool) -> str:
        try:
            import torch
            if gpu_enabled and torch.cuda.is_available():
                return 'cuda:0'
        except Exception:
            pass
        return 'cpu'

    def warmup(self):
        import numpy as np
        from ultralytics import YOLO
        with self._lock:
            self._model = YOLO('%s.pt' % self._model_name)
            self._model.to(self._device)
            self._model.predict(np.zeros((640, 640, 3), dtype='uint8'), imgsz=640, verbose=False)
            self._healthy = True
        logger.info('YOLO %s loaded on %s', self._model_name, self._device)

    def infer(self, frame, *, imgsz: int = 640, conf: float = 0.35, classes=None) -> list[Detection]:
        if self._model is None:
            self.warmup()
        with self._lock:
            res = self._model.predict(
                frame, imgsz=imgsz, conf=conf, classes=classes,
                device=self._device, half=(self._device != 'cpu'), verbose=False)[0]
        names = res.names or {}
        out = []
        for b in res.boxes:
            xyxy = tuple(float(v) for v in b.xyxy[0].tolist())
            cid = int(b.cls[0])
            out.append(Detection(xyxy, float(b.conf[0]), cid, names.get(cid, str(cid))))
        return out

    def benchmark(self, sample) -> dict:
        if self._model is None:
            self.warmup()
        n = 10
        t0 = time.monotonic()
        for _ in range(n):
            self.infer(sample, imgsz=self._spec.get('imgsz', 640))
        dt = time.monotonic() - t0
        fps = n / dt if dt > 0 else 0.0
        vram = 0
        try:
            import torch
            if self._device != 'cpu':
                vram = int(torch.cuda.memory_reserved() / (1024 * 1024))
        except Exception:
            pass
        target = max(1, self._spec.get('target_fps', 5))
        return {'fps_per_cam': round(fps, 1), 'vram_mb': vram, 'capacity': max(1, int(fps // target))}

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def device(self) -> str:
        return self._device

    def close(self):
        self._model = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
