"""go2rtc REST driver (PLAN P1 §5.6). Backend-only; browsers never hit go2rtc directly."""
import time

import requests

import config


class Go2rtcError(Exception):
    pass


class Go2rtcDriver:
    def __init__(self, base_url: str | None = None, timeout: int = 5):
        self.base_url = (base_url or config.GO2RTC_URL).rstrip('/')
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return self.base_url + path

    def healthz(self) -> bool:
        try:
            return requests.get(self._url('/api'), timeout=self.timeout).status_code == 200
        except requests.RequestException:
            return False

    def list_streams(self) -> dict:
        try:
            r = requests.get(self._url('/api/streams'), timeout=self.timeout)
            r.raise_for_status()
            return r.json() or {}
        except (requests.RequestException, ValueError) as e:
            raise Go2rtcError(str(e))

    def put_stream(self, name: str, src: str) -> None:
        """Register/replace a stream's source. go2rtc registers the stream even when
        the source isn't reachable yet (returning 400) — actual producer state is
        tracked separately by the health task — so only a transport error is fatal."""
        try:
            r = requests.put(self._url('/api/streams'), params={'name': name, 'src': src},
                             timeout=self.timeout)
        except requests.RequestException as e:
            raise Go2rtcError(str(e))
        if r.status_code >= 500:
            raise Go2rtcError('put_stream %s -> http %s' % (name, r.status_code))

    def delete_stream(self, name: str) -> None:
        try:
            requests.delete(self._url('/api/streams'), params={'src': name}, timeout=self.timeout)
        except requests.RequestException as e:
            raise Go2rtcError(str(e))

    def stream_status(self, name: str) -> dict:
        """Producer/consumer counts for one stream (for health)."""
        try:
            r = requests.get(self._url('/api/streams'), params={'src': name}, timeout=self.timeout)
            if r.status_code != 200:
                return {}
            data = r.json() or {}
        except (requests.RequestException, ValueError):
            return {}
        producers = data.get('producers') or []
        consumers = data.get('consumers') or []
        return {'producers': len(producers), 'consumers': len(consumers), 'online': len(producers) > 0}

    def get_frame(self, name: str, width: int | None = None,
                  retries: int = 3, good_bytes: int = 8000) -> bytes | None:
        """Single JPEG frame via go2rtc (snapshot/thumbnail). `width` scales the output (go2rtc
        `w=`), keeping a 4K source cheap to cache as a tile.

        go2rtc's on-demand frame endpoint cold-starts the source on each grab; for an H.265 cam
        whose live stream is transcoded that means the first decoded frame can land BEFORE a
        keyframe → a gray/garbage (and tiny) JPEG. A real scene compresses far larger than a
        flat broken frame, so we grab a few times and keep the largest, returning as soon as one
        looks like a real picture. We only retry when the source IS up (a small valid JPEG came
        back) — a transport error / non-200 means the camera is unreachable, so we bail at once
        and never slow the offline path."""
        params: dict = {'src': name}
        if width:
            params['w'] = width
        best = None
        for attempt in range(max(1, retries)):
            try:
                r = requests.get(self._url('/api/frame.jpeg'), params=params, timeout=self.timeout)
            except requests.RequestException:
                return best
            if r.status_code != 200:
                return best
            content = r.content
            # JPEG starts with the SOI marker 0xFFD8; anything else isn't a frame at all
            if not (content and len(content) >= 512 and content[:2] == b'\xff\xd8'):
                return best
            if best is None or len(content) > len(best):
                best = content
            if len(content) >= good_bytes:
                return best                      # a real picture — done
            if attempt < retries - 1:
                time.sleep(0.4)                  # let the source push past a keyframe, retry
        return best
