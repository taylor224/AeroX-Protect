import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import { acquireStartSlot } from '@/pages/live/connectGate';
import { getWsTicket, liveMp4Url, liveWsUrl, webrtcExchange } from '@/pages/live/live.api';
import { connectMse, mseSupported } from '@/pages/live/mseStream';
import { getIceServers } from '@/pages/live/portal.api';
import type { RatioMode } from '@/types/axp';

const RATIO_CLASS: Record<RatioMode, string> = {
  fit: 'object-contain',
  stretch: 'object-fill',
  crop: 'object-cover',
};

type PlayerState = 'connecting' | 'webrtc' | 'ws' | 'mp4' | 'error';

// An on-demand H.265→H.264 transcode cold-starts and must wait for the first keyframe, which
// can take >10s on a loaded box. Too short a stall window here fires the watchdog mid-startup,
// tearing down and restarting the transcode in a loop (never stabilises). Give it real room.
const WATCHDOG_STALL_MS = 15000;

// A transient WebSocket drop (go2rtc restart/self-heal, brief network blip) should reconnect
// the same MSE path a couple of times before downgrading — a single hiccup shouldn't strand
// the tile on the higher-latency fMP4 fallback until the next watchdog reload.
const MSE_MAX_RETRIES = 2;

/**
 * Live engine, in order of preference (mirrors Frigate, which drives the same go2rtc engine):
 *   1. MSE/WebSocket — PRIMARY. Plain TCP through nginx straight to go2rtc: no ICE, no UDP
 *                      port-forwarding, no candidate juggling, and it doesn't drop frames.
 *                      Works on the LAN and from remote networks (TURN-free).
 *   2. WebRTC        — fallback only. Lowest latency but fragile (needs ICE + UDP 8555 and
 *                      correctly-advertised candidates), so it's used when MSE is unsupported
 *                      (old iPhone Safari) or has failed, and we bail to fMP4 fast on trouble.
 *   3. fMP4 stream   — universal HTTP last resort, no WebSocket required.
 * Every path goes through the JWT+scope-guarded proxy — the browser never reaches go2rtc directly.
 */
export function VideoPlayer({
  go2rtcName,
  ratioMode = 'fit',
  active = true,
  muted = true,
}: {
  go2rtcName: string;
  ratioMode?: RatioMode;
  active?: boolean;
  muted?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<PlayerState>('connecting');
  const [reloadKey, setReloadKey] = useState(0); // bumped by the stall watchdog to re-init
  const stallLimitRef = useRef(WATCHDOG_STALL_MS); // doubles per consecutive reload (no reconnect storm)

  // tear down streams while the tab is hidden — N background tiles otherwise keep
  // decoding/buffering and the watchdog reload-loops with nobody watching
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const onVis = () => setPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  // toggle audio without tearing down the stream (unmuting after a click is autoplay-safe)
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = muted;
    if (!muted) void v.play().catch(() => {});
  }, [muted]);

  useEffect(() => {
    if (!active || !pageVisible) return;
    const video = videoRef.current;
    if (!video) return;
    let cancelled = false;
    let settled = false; // a transport owns the <video> element
    let webrtcLive = false; // WebRTC delivered media — don't let the timeout tear it down
    let mseRetries = 0;
    let pc: RTCPeerConnection | null = null;
    let wsTeardown: (() => void) | null = null;
    let webrtcTimer = 0;

    const closePc = () => {
      if (pc) {
        pc.close();
        pc = null;
      }
    };
    const clearWs = () => {
      if (wsTeardown) {
        wsTeardown();
        wsTeardown = null;
      }
    };

    const fallbackToMp4 = () => {
      if (cancelled) return;
      settled = true;
      window.clearTimeout(webrtcTimer);
      clearWs();
      closePc();
      video.srcObject = null;
      video.src = liveMp4Url(go2rtcName);
      setState('mp4');
      void video.play().catch(() => setState('error'));
    };

    // PRIMARY transport. On a transient drop, reconnect MSE a couple of times before
    // handing off to the WebRTC/fMP4 fallbacks (see MSE_MAX_RETRIES).
    const tryWs = async () => {
      if (cancelled || settled) return;
      if (!mseSupported()) {
        void tryWebRTC(); // old iPhone Safari has no MSE — go straight to the WebRTC fallback
        return;
      }
      settled = true;
      closePc();
      video.srcObject = null;
      setState('connecting');
      try {
        const { ticket } = await getWsTicket(go2rtcName);
        if (cancelled) return;
        wsTeardown = connectMse(video, liveWsUrl(go2rtcName, ticket), {
          onPlaying: () => {
            if (cancelled) return;
            mseRetries = 0; // a clean start resets the reconnect budget
            setState('ws');
          },
          onError: () => {
            clearWs();
            if (cancelled) return;
            settled = false;
            if (mseRetries < MSE_MAX_RETRIES) {
              mseRetries++;
              window.setTimeout(() => {
                if (!cancelled) void tryWs();
              }, 500 * mseRetries); // brief, growing backoff
            } else {
              void tryWebRTC();
            }
          },
        });
      } catch {
        settled = false;
        void tryWebRTC();
      }
    };

    // FALLBACK transport. Fragile (ICE + UDP 8555), so we give it a short window and drop to
    // the universal fMP4 stream on any failure rather than retrying a doomed PeerConnection.
    const tryWebRTC = async () => {
      if (cancelled || settled) return;
      settled = true;
      clearWs();
      video.srcObject = null;
      setState('connecting');
      // overall deadline: if WebRTC hasn't delivered media shortly, don't hang on it
      webrtcTimer = window.setTimeout(() => {
        if (!cancelled && !webrtcLive) fallbackToMp4();
      }, 3000);
      try {
        pc = new RTCPeerConnection({ iceServers: await getIceServers() });
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });
        pc.ontrack = (e) => {
          if (cancelled) return;
          window.clearTimeout(webrtcTimer);
          webrtcLive = true;
          video.srcObject = e.streams[0];
          setState('webrtc');
          void video.play().catch(() => {});
        };
        pc.oniceconnectionstatechange = () => {
          if (!pc || cancelled) return;
          if (pc.iceConnectionState === 'failed') {
            webrtcLive = false;
            fallbackToMp4(); // remote NAT w/o TURN (or mid-stream drop) → universal path
          }
        };
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const answer = await webrtcExchange(go2rtcName, offer.sdp ?? '');
        if (cancelled) return;
        if (!answer) {
          fallbackToMp4();
          return;
        }
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      } catch {
        fallbackToMp4();
      }
    };

    // start on the primary transport (or the WebRTC fallback when MSE is unsupported), but
    // stagger the start across tiles so a full page doesn't connect all at once. The spinner
    // shows during the brief wait; the watchdog stays idle until a path is actually live.
    void acquireStartSlot().then(() => {
      if (cancelled) return;
      if (mseSupported()) void tryWs();
      else void tryWebRTC();
    });

    // stall watchdog: live video should always advance. If a path has taken over but
    // playback freezes (MSE buffer gap, WebRTC track stall, transcode keyframe hiccup) for
    // the stall window, tear everything down and re-init from scratch — auto-recovers cuts.
    let lastT = -1;
    let lastProgress = Date.now();
    const watchdog = window.setInterval(() => {
      if (cancelled) return;
      const live = webrtcLive || settled;     // a real path is up (not the initial connect)
      const t = video.currentTime;
      if (!live || video.paused) { lastProgress = Date.now(); lastT = t; return; }
      if (t > lastT + 0.05) {
        lastT = t;
        lastProgress = Date.now();
        stallLimitRef.current = WATCHDOG_STALL_MS;   // playing again → reset the backoff
        return;
      }
      if (Date.now() - lastProgress > stallLimitRef.current) {
        lastProgress = Date.now();
        // back off: a feed that stalls right after every reload shouldn't reconnect-storm
        stallLimitRef.current = Math.min(stallLimitRef.current * 2, 60_000);
        setReloadKey((k) => k + 1);          // re-runs this effect → fresh connect attempt
      }
    }, 2500);

    return () => {
      cancelled = true;
      window.clearTimeout(webrtcTimer);
      window.clearInterval(watchdog);
      clearWs();
      closePc();
      if (video) {
        video.srcObject = null;
        video.removeAttribute('src');
        video.load();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [go2rtcName, active, pageVisible, reloadKey]);

  return (
    <div className="relative h-full w-full bg-black">
      <video
        ref={videoRef}
        autoPlay
        muted={muted}
        playsInline
        className={cn('h-full w-full', RATIO_CLASS[ratioMode])}
      />
      {state === 'connecting' && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        </div>
      )}
      {state === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-white/50">
          연결할 수 없습니다
        </div>
      )}
    </div>
  );
}
