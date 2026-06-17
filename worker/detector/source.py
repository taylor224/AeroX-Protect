"""go2rtc frame source (PLAN P4 §6.1, runway_monitor camera.py generalized). Pulls the
camera's shared go2rtc re-stream over RTSP via OpenCV, dropping to the latest frame so
inference at target_fps never backs up. cv2/numpy are lazy (container-only)."""
import logging
import time

logger = logging.getLogger(__name__)


class Go2rtcSource:
    def __init__(self, rtsp_url: str, target_fps: int = 5):
        self.rtsp_url = rtsp_url
        self.target_fps = max(1, target_fps)
        self._cap = None
        self._frame_id = 0

    def open(self):
        import cv2
        self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def read(self):
        """Return (frame, frame_id, wallclock_ms) or (None, frame_id, ms) if unavailable."""
        if self._cap is None:
            self.open()
        ok, frame = self._cap.read() if self._cap is not None else (False, None)
        ms = int(time.time() * 1000)
        if not ok or frame is None:
            return None, self._frame_id, ms
        self._frame_id += 1
        return frame, self._frame_id, ms

    @staticmethod
    def frame_size(frame) -> tuple[int, int]:
        h, w = frame.shape[:2]
        return int(w), int(h)

    def close(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
