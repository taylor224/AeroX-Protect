"""Track-aware detection down-sampling (PLAN P4 §6.7) — bound `detections` row growth:
report a track on creation, on loss, and once per sample_interval while sustained. The
trigger/zone-entry moments are always reported by the pipeline (passed force=True)."""


class TrackSampler:
    def __init__(self, interval_ms: int = 1000):
        self.interval = interval_ms
        self._last: dict[str, int] = {}

    def sample(self, tracks: list, ts_ms: int) -> list:
        out = []
        for t in tracks:
            tk = t.track_key
            if getattr(t, 'is_new', False) or getattr(t, 'is_lost', False) or getattr(t, 'force', False):
                out.append(t)
                self._last[tk] = ts_ms
            elif ts_ms - self._last.get(tk, -10 ** 15) >= self.interval:
                out.append(t)
                self._last[tk] = ts_ms
        # forget lost tracks so a recycled key re-reports immediately
        for t in tracks:
            if getattr(t, 'is_lost', False):
                self._last.pop(t.track_key, None)
        return out
