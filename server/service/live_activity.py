"""Live-viewer activity tracking — idle-stop for live transcodes.

Two complementary signals decide "someone is watching this live stream":
- the live endpoints (ws-ticket / webrtc / mp4) mark() at connection start, which
  covers the 1-2s before go2rtc registers the new consumer;
- the recorder supervisor re-marks every tick while go2rtc reports a real consumer,
  which covers multi-hour watches that never re-issue a ticket.

is_active() gates the keep-warm consumer (recorder supervisor) and encoder-node
assignments (encode scheduler). A Redis failure fails OPEN (treated as active) —
a Redis blip must never black out live viewing.
"""
import logging
import time

import config

logger = logging.getLogger(__name__)

KEY_PREFIX = '%s:live:act:' % config.REDIS_KEY_PREFIX
DEFAULT_IDLE_S = 300


def idle_window() -> int:
    """Idle-stop window in seconds. 0 disables idle-stop (always-warm, the old behavior)."""
    from server.model.setting import Setting
    try:
        return int(Setting.get_value('live_transcode_idle_s', DEFAULT_IDLE_S) or 0)
    except Exception:
        return DEFAULT_IDLE_S


def mark(go2rtc_name: str, window: int | None = None) -> None:
    """Record viewer activity on a live stream (best-effort, never raises)."""
    from server.service.token import get_redis
    w = idle_window() if window is None else window
    if w <= 0:
        return
    try:
        get_redis().set(KEY_PREFIX + go2rtc_name, int(time.time()), ex=max(15, w))
    except Exception as e:
        logger.debug('live activity mark failed for %s: %s', go2rtc_name, e)


def is_active(go2rtc_name: str, window: int | None = None) -> bool:
    """Whether the stream saw a viewer within the idle window. Fails open on Redis error."""
    from server.service.token import get_redis
    w = idle_window() if window is None else window
    if w <= 0:
        return True
    try:
        return get_redis().exists(KEY_PREFIX + go2rtc_name) == 1
    except Exception as e:
        logger.debug('live activity check failed for %s (fail-open): %s', go2rtc_name, e)
        return True
