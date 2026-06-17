/**
 * MSE-over-WebSocket live engine (go2rtc protocol).
 *
 * The browser opens a WebSocket to nginx (which proxies to go2rtc's /api/ws after validating
 * a ticket), announces the MSE codecs it supports, and go2rtc streams back fMP4 fragments:
 * the first binary message is the init segment, the rest are media segments. We feed them
 * into a MediaSource SourceBuffer. This is low-latency AND TURN-free — only a TCP WebSocket
 * is needed, so it works from remote networks where WebRTC would need a TURN relay.
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

/**
 * Start an MSE/WebSocket stream into `video`. Returns a teardown function. `onPlaying` fires
 * once playback actually starts; `onError` fires on any failure so the caller can fall back.
 */
export function connectMse(video: HTMLVideoElement, wsUrl: string, opts: MseOpts = {}): () => void {
  let stopped = false;
  let ws: WebSocket | null = null;
  let ms: MediaSource | null = null;
  let sb: SourceBuffer | null = null;
  const queue: ArrayBuffer[] = [];
  let objectUrl = '';

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
  // what froze playback before: a remove consumed the updateend the pending append was
  // waiting for, the queue grew unbounded, and the picture stalled.
  const flush = () => {
    if (!sb || sb.updating || queue.length === 0) return;
    const chunk = queue[0];
    try {
      sb.appendBuffer(chunk);
      queue.shift();
    } catch (e) {
      if ((e as DOMException)?.name === 'QuotaExceededError') {
        // buffer full — evict all but the last few seconds, retry the same chunk on updateend
        try {
          const end = sb.buffered.length ? sb.buffered.end(sb.buffered.length - 1) : 0;
          sb.remove(0, Math.max(0.1, end - 4));
        } catch {
          fail();
        }
      } else {
        fail();
      }
    }
  };

  // Keep only a short tail buffered so live latency and memory stay bounded. Never remove
  // up to the playhead — yanking the region being decoded restarts the decoder (visible
  // breakup) and can drop the playhead out of the buffer.
  const trim = () => {
    if (!sb || sb.updating || sb.buffered.length === 0) return;
    const start = sb.buffered.start(0);
    const end = sb.buffered.end(sb.buffered.length - 1);
    const cut = Math.min(end - 6, video.currentTime - 2);
    if (end - start > 12 && cut > start) {
      try {
        sb.remove(start, cut);
      } catch {
        /* remove can throw if the buffer is busy; ignore and retry next pass */
      }
    }
  };

  // Keep the playhead at the live edge. Runs on a timer (not per-updateend) so it can't
  // fight in-flight buffer operations, and only seeks on real drift/gap — every needless
  // seek forces the decoder to resync to the next keyframe (gray/blocky frames).
  const keepLive = () => {
    if (stopped || !sb || sb.updating || sb.buffered.length === 0) return;
    const start = sb.buffered.start(0);
    const end = sb.buffered.end(sb.buffered.length - 1);
    if (video.currentTime < start || end - video.currentTime > 3) {
      try {
        video.currentTime = Math.max(start, end - 0.5);
      } catch {
        /* setting currentTime can throw mid-update; harmless, retry next tick */
      }
    }
  };
  const liveTimer = window.setInterval(keepLive, 2000);

  try {
    ms = new MediaSource();
  } catch {
    opts.onError?.();
    return () => undefined;
  }
  objectUrl = URL.createObjectURL(ms);
  video.src = objectUrl;

  ms.addEventListener('sourceopen', () => {
    if (stopped || !ms) return;
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      fail();
      return;
    }
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => ws?.send(JSON.stringify({ type: 'mse', value: supportedCodecs() }));
    ws.onerror = fail;
    ws.onclose = () => {
      if (!stopped) fail();
    };
    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === 'string') {
        let msg: { type?: string; value?: string };
        try {
          msg = JSON.parse(ev.data) as { type?: string; value?: string };
        } catch {
          return;
        }
        if (msg.type === 'mse' && msg.value && ms && ms.readyState === 'open' && !sb) {
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
        } else if (msg.type === 'error') {
          fail();
        }
        return;
      }
      queue.push(ev.data as ArrayBuffer); // binary fMP4 fragment
      flush();
    };
  });

  video.addEventListener('playing', onPlaying, { once: true });
  void video.play().catch(() => {
    /* autoplay may reject until data arrives; the 'playing' event still fires once it does */
  });

  function teardown() {
    stopped = true;
    window.clearInterval(liveTimer);
    video.removeEventListener('playing', onPlaying);
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
