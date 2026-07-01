/**
 * MSE-over-WebSocket live engine (go2rtc protocol).
 *
 * The browser opens a WebSocket to nginx (which proxies to go2rtc's /api/ws after validating
 * a ticket), announces the MSE codecs it supports, and go2rtc streams back fMP4 fragments:
 * the first binary message is the init segment, the rest are media segments. We feed them
 * into a MediaSource SourceBuffer. This is low-latency AND TURN-free — only a TCP WebSocket
 * is needed, so it works from remote networks where WebRTC would need a TURN relay.
 *
 * On a transient drop (go2rtc self-heal/restart, brief network blip) the WebSocket is
 * reconnected in-place at a 10s cadence WITHOUT tearing down the MediaSource/decoder — the
 * SourceBuffer is re-initialised by go2rtc's fresh init segment. This avoids the
 * multi-second black "cut out" (and transcode cold-start) a full rebuild causes.
 */

// Candidate MSE codecs, most-capable first. We send the subset the browser actually supports;
// go2rtc replies with the concrete `video/mp4; codecs="…"` mimeType to use for the SourceBuffer.
const MSE_CODECS = [
  'avc1.640029', 'avc1.64002A', 'avc1.640033', 'avc1.42E01E',
  'hvc1.1.6.L153.B0', 'hev1.1.6.L153.B0',
  'mp4a.40.2', 'mp4a.40.5', 'mp4a.67', 'flac', 'opus',
];

function supportedCodecs(): string {
  if (typeof MediaSource === 'undefined' || typeof MediaSource.isTypeSupported !== 'function') return '';
  return MSE_CODECS.filter((c) => MediaSource.isTypeSupported(`video/mp4; codecs="${c}"`)).join();
}

/** True if this browser can play MSE fMP4 (desktop + iPad; not iPhone Safari). */
export function mseSupported(): boolean {
  return supportedCodecs() !== '';
}

interface MseOpts {
  onPlaying?: () => void;
  onError?: () => void;
}

// Never reconnect faster than this — a flaky link must not storm go2rtc (each reconnect is a
// new ticket + nginx auth_request + go2rtc consumer). A 10s floor keeps reconnects tame.
const RECONNECT_CADENCE_MS = 10_000;
const MAX_RECONNECTS = 6; // ~1min of retries before giving up to the WebRTC/fMP4 fallback

/**
 * Start an MSE/WebSocket stream into `video`. `getUrl` returns a fresh WS URL (with a fresh,
 * short-lived ticket) for each connect attempt. Returns a teardown function. `onPlaying`
 * fires once playback actually starts; `onError` only fires after reconnects are exhausted.
 */
export function connectMse(video: HTMLVideoElement, getUrl: () => Promise<string>, opts: MseOpts = {}): () => void {
  let stopped = false;
  let ws: WebSocket | null = null;
  let ms: MediaSource | null = null;
  let sb: SourceBuffer | null = null;
  const queue: ArrayBuffer[] = [];
  let objectUrl = '';
  let mediaFlowing = false; // received media since the last (re)connect
  let reconnects = 0;
  let lastConnectAt = 0;
  let reconnectTimer = 0;

  const onPlaying = () => {
    if (!stopped) opts.onPlaying?.();
  };

  const fail = () => {
    if (stopped) return;
    teardown();
    opts.onError?.();
  };

  // Exactly ONE SourceBuffer operation (append/remove) may be in flight at a time; every
  // operation ends with an `updateend`, which drains the queue first and only does
  // housekeeping (trim) when idle. Interleaving append/remove/seek in the same tick is
  // what froze playback before.
  const flush = () => {
    if (!sb || sb.updating || queue.length === 0) return;
    const chunk = queue[0];
    try {
      sb.appendBuffer(chunk);
      queue.shift();
    } catch (e) {
      if ((e as DOMException)?.name === 'QuotaExceededError') {
        // buffer full — evict everything except the last ~10s, retry the same chunk on updateend
        try {
          const end = sb.buffered.length ? sb.buffered.end(sb.buffered.length - 1) : 0;
          sb.remove(0, Math.max(0.1, end - 10));
        } catch {
          fail();
        }
      } else {
        fail();
      }
    }
  };

  // Keep a healthy ~15-30s tail buffered so jitter/reconnects don't underrun. Never remove up
  // to the playhead. A generous buffer + playback-rate catch-up (below) replaces the old
  // seek-to-live approach, which forced a decoder keyframe resync (gray/blocky) on every drift.
  const trim = () => {
    if (!sb || sb.updating || sb.buffered.length === 0) return;
    const start = sb.buffered.start(0);
    const end = sb.buffered.end(sb.buffered.length - 1);
    const cut = Math.min(end - 15, video.currentTime - 10);
    if (video.currentTime - start > 30 && cut > start) {
      try {
        sb.remove(start, cut);
      } catch {
        /* remove can throw if the buffer is busy; ignore and retry next pass */
      }
    }
  };

  // Bound live latency by nudging the PLAYBACK RATE (smooth, no keyframe resync) instead of
  // seeking. Only hard-seek when the playhead has genuinely fallen out of the buffered range
  // (a real gap, e.g. after a reconnect) or drift is absurd.
  const keepLive = () => {
    if (stopped || !sb || sb.buffered.length === 0) return;
    const start = sb.buffered.start(0);
    const end = sb.buffered.end(sb.buffered.length - 1);
    if (video.currentTime < start || video.currentTime > end + 1) {
      try {
        video.currentTime = Math.max(start, end - 2); // fell out of buffer → resync to live tail
      } catch {
        /* setting currentTime can throw mid-update; harmless */
      }
      return;
    }
    const drift = end - video.currentTime;
    if (drift > 30) {
      try {
        video.currentTime = end - 2; // pathological drift → one seek back to live
      } catch {
        /* ignore */
      }
      video.playbackRate = 1.0;
    } else if (drift > 6) {
      video.playbackRate = 1.3; // catch up smoothly
    } else if (drift > 3) {
      video.playbackRate = 1.1;
    } else {
      video.playbackRate = 1.0;
    }
  };
  const liveTimer = window.setInterval(keepLive, 1000);

  const scheduleReconnect = () => {
    if (stopped) return;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* already closing */
      }
      ws = null;
    }
    if (reconnects >= MAX_RECONNECTS) {
      fail();
      return;
    }
    reconnects++;
    const wait = Math.max(0, RECONNECT_CADENCE_MS - (Date.now() - lastConnectAt));
    window.clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(() => {
      if (!stopped) void openWs();
    }, wait);
  };

  const openWs = async () => {
    if (stopped || !ms) return;
    mediaFlowing = false;
    lastConnectAt = Date.now();
    let url: string;
    try {
      url = await getUrl();
    } catch {
      scheduleReconnect();
      return;
    }
    if (stopped || !ms) return;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => ws?.send(JSON.stringify({ type: 'mse', value: supportedCodecs() }));
    ws.onerror = () => {
      /* surfaced via onclose */
    };
    ws.onclose = () => {
      if (!stopped) scheduleReconnect();
    };
    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === 'string') {
        let msg: { type?: string; value?: string };
        try {
          msg = JSON.parse(ev.data) as { type?: string; value?: string };
        } catch {
          return;
        }
        if (msg.type === 'mse' && msg.value && ms && ms.readyState === 'open') {
          // First connect: create the SourceBuffer. Reconnect: reuse it — go2rtc re-sends an
          // init segment which MSE uses to re-initialise the SAME buffer (same codec), so the
          // decoder is preserved across the drop.
          if (!sb) {
            try {
              sb = ms.addSourceBuffer(msg.value);
              sb.mode = 'segments';
              sb.addEventListener('updateend', () => {
                if (queue.length > 0) {
                  flush(); // drain incoming media first; housekeeping waits until idle
                  return;
                }
                trim();
              });
            } catch {
              fail();
            }
          }
        } else if (msg.type === 'error') {
          scheduleReconnect(); // stream-level error → try to reconnect rather than give up
        }
        return;
      }
      if (!mediaFlowing) {
        mediaFlowing = true;
        reconnects = 0; // real media is flowing again → reset the reconnect budget
      }
      queue.push(ev.data as ArrayBuffer); // binary fMP4 fragment
      flush();
    };
  };

  try {
    ms = new MediaSource();
  } catch {
    opts.onError?.();
    return () => undefined;
  }
  objectUrl = URL.createObjectURL(ms);
  video.src = objectUrl;

  ms.addEventListener('sourceopen', () => {
    if (!stopped) void openWs();
  });

  video.addEventListener('playing', onPlaying, { once: true });
  void video.play().catch(() => {
    /* autoplay may reject until data arrives; the 'playing' event still fires once it does */
  });

  function teardown() {
    stopped = true;
    window.clearInterval(liveTimer);
    window.clearTimeout(reconnectTimer);
    video.removeEventListener('playing', onPlaying);
    try {
      video.playbackRate = 1.0;
    } catch {
      /* ignore */
    }
    if (ws) {
      try {
        ws.close();
      } catch {
        /* already closing */
      }
      ws = null;
    }
    if (ms && ms.readyState === 'open') {
      try {
        ms.endOfStream();
      } catch {
        /* not in a state to end */
      }
    }
    sb = null;
    ms = null;
    queue.length = 0;
    if (objectUrl) {
      try {
        URL.revokeObjectURL(objectUrl);
      } catch {
        /* ignore */
      }
      objectUrl = '';
    }
    video.removeAttribute('src');
    try {
      video.load();
    } catch {
      /* ignore */
    }
  }

  return teardown;
}
