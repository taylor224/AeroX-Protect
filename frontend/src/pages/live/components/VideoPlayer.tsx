import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';
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

// WebRTC reachability is a property of the network, not of one camera: when ICE fails for
// one tile it will fail for all of them. Remember the failure so subsequent connects (other
// tiles, watchdog reloads) skip the WebRTC probe window and start on MSE/WS immediately,
// instead of every tile burning seconds on a doomed PeerConnection.
let webrtcFailedAt = 0;
const WEBRTC_RETRY_MS = 5 * 60_000;

// An on-demand H.265→H.264 transcode cold-starts and must wait for the first keyframe, which
// can take >8s on a loaded box. Too short a stall window here fires the watchdog mid-startup,
// tearing down and restarting the transcode in a loop (never stabilises). Give it real room.
const WATCHDOG_STALL_MS = 15000;

/**
 * Live engine, in order of preference:
 *   1. WebRTC      — lowest latency, passthrough (best on LAN; needs TURN to traverse some
 *                    remote NATs, hence the timeout/ICE-failure fallback)
 *   2. MSE/WebSocket — low latency AND TURN-free; works from remote networks over plain TCP
 *   3. fMP4 stream — universal HTTP fallback, no WebSocket required
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
    let settled = false; // a non-WebRTC path has taken over
    let webrtcLive = false; // WebRTC delivered media — don't let the timeout tear it down
    let pc: RTCPeerConnection | null = null;
    let wsTeardown: (() => void) | null = null;

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
      clearWs();
      closePc();
      video.srcObject = null;
      video.src = liveMp4Url(go2rtcName);
      setState('mp4');
      void video.play().catch(() => setState('error'));
    };

    const tryWs = async () => {
      if (cancelled || settled) return;
      if (attemptedWebrtc) webrtcFailedAt = Date.now(); // WebRTC was tried and didn't deliver
      if (!mseSupported()) {
        fallbackToMp4();
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
            if (!cancelled) setState('ws');
          },
          onError: () => {
            settled = false; // allow the mp4 fallback to take over
            fallbackToMp4();
          },
        });
      } catch {
        settled = false;
        fallbackToMp4();
      }
    };

    const tryWebRTC = async () => {
      try {
        pc = new RTCPeerConnection({ iceServers: await getIceServers() });
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });
        pc.ontrack = (e) => {
          if (cancelled || settled) return;
          webrtcLive = true;
          video.srcObject = e.streams[0];
          setState('webrtc');
          void video.play().catch(() => {});
        };
        pc.oniceconnectionstatechange = () => {
          if (!pc || cancelled || settled) return;
          if (pc.iceConnectionState === 'failed') {
            webrtcLive = false;
            void tryWs(); // remote NAT w/o TURN (or mid-stream drop) → switch fast
          }
        };
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const answer = await webrtcExchange(go2rtcName, offer.sdp ?? '');
        if (cancelled) return;
        if (!answer) {
          void tryWs();
          return;
        }
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      } catch {
        void tryWs();
      }
    };

    // give WebRTC a short window to deliver media, else move to the TURN-free WS path.
    // If WebRTC recently failed on this network, skip the probe entirely.
    let timer = 0;
    let attemptedWebrtc = false;
    if (Date.now() - webrtcFailedAt < WEBRTC_RETRY_MS) {
      void tryWs();
    } else {
      attemptedWebrtc = true;
      void tryWebRTC();
      timer = window.setTimeout(() => {
        if (!cancelled && !settled && !webrtcLive) void tryWs();
      }, 3000);
    }

    // stall watchdog: live video should always advance. If a path has taken over but
    // playback freezes (WebRTC track stalls, MSE buffer gap, transcode keyframe hiccup) for
    // ~8s, tear everything down and re-init from scratch — auto-recovers the occasional cut.
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
      window.clearTimeout(timer);
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
