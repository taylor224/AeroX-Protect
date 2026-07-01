import type HlsType from 'hls.js';
import { useEffect, useMemo, useRef, useState } from 'react';

import { hlsUrl } from '@/pages/playback/playback.api';
import type { Segment } from '@/types/p2';

/**
 * Continuous recorded-playback via hls.js over a VOD playlist. The whole
 * requested range plays as ONE MSE-backed stream, so there is no per-segment reload/stall and
 * seeking works across segment boundaries and gaps. H.265 recordings are transcoded to H.264
 * server-side for browsers that can't decode HEVC.
 *
 * The playlist compresses gaps (#EXT-X-DISCONTINUITY), so media `currentTime` is NOT wall time.
 * We map between them with the segment list (same order/durations the server built the playlist
 * from): cumulative media offset ↔ real timestamp.
 */
export function Player({
  cameraUuid,
  from,
  to,
  segments,
  seekTs,
  onTimeUpdate,
}: {
  cameraUuid: string;
  from: number;
  to: number;
  segments: Segment[];
  seekTs: number | null;
  onTimeUpdate?: (ts: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<HlsType | null>(null);
  const lastEmitted = useRef<number | null>(null); // playhead we pushed up (ignore the echo)
  const [error, setError] = useState(false);

  // does this browser need a server-side H.264 transcode? (recording is HEVC + no HEVC in MSE)
  const needsTranscode = useMemo(() => {
    const hasHevc = segments.some((s) => s.video_codec === 'h265' || s.video_codec === 'hevc');
    if (!hasHevc) return false;
    const hevcOk =
      typeof MediaSource !== 'undefined' &&
      MediaSource.isTypeSupported('video/mp4; codecs="hvc1.1.6.L93.B0"');
    return !hevcOk;
  }, [segments]);

  // cumulative media-time ↔ wall-clock map (gap-aware). rows[i].mediaStart = seconds into the
  // MSE timeline where segment i begins; .start/.end are its wall-clock epoch-ms bounds.
  const rows = useMemo(() => {
    let acc = 0;
    return segments.map((s) => {
      const row = { start: s.start_ts, end: s.end_ts, dur: (s.duration_ms || 10000) / 1000, mediaStart: acc };
      acc += row.dur;
      return row;
    });
  }, [segments]);

  const wallToMedia = (ts: number): number => {
    for (const r of rows) {
      if (ts < r.end) return r.mediaStart + Math.max(0, (ts - r.start) / 1000); // in-seg, or snap fwd across a gap
    }
    return rows.length ? rows[rows.length - 1].mediaStart + rows[rows.length - 1].dur : 0;
  };
  const mediaToWall = (mt: number): number => {
    for (const r of rows) {
      if (mt < r.mediaStart + r.dur) return r.start + Math.max(0, mt - r.mediaStart) * 1000;
    }
    return to;
  };

  // (re)build the stream when the range/source changes — NOT on seekTs (that's handled below,
  // seamlessly, without tearing down the stream).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || segments.length === 0) return;
    setError(false);
    let cancelled = false;
    const src = hlsUrl(cameraUuid, from, to, needsTranscode);
    const startMedia = seekTs != null ? wallToMedia(seekTs) : 0;

    const seekAndPlay = () => {
      try {
        if (startMedia > 0) video.currentTime = startMedia;
      } catch {
        /* seeking before buffered — harmless */
      }
      void video.play().catch(() => {
        /* autoplay may reject; the element is muted+controls so the user can start it */
      });
    };

    // hls.js is loaded on demand (kept out of the initial bundle — only the recorded-playback
    // views need it).
    void import('hls.js').then(({ default: Hls }) => {
      if (cancelled || !videoRef.current) return;
      if (Hls.isSupported()) {
        const hls = new Hls({ enableWorker: true, lowLatencyMode: false, maxBufferLength: 30, backBufferLength: 90 });
        hlsRef.current = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, seekAndPlay);
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!data.fatal) return;
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
          else {
            hls.destroy();
            hlsRef.current = null;
            setError(true);
          }
        });
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // native HLS (Safari / iOS)
        video.src = src;
        video.addEventListener('loadedmetadata', seekAndPlay, { once: true });
        video.addEventListener('error', () => setError(true), { once: true });
      } else {
        setError(true);
      }
    });

    return () => {
      cancelled = true;
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      video.removeAttribute('src');
      try {
        video.load();
      } catch {
        /* ignore */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraUuid, from, to, needsTranscode, segments.length]);

  // real (click) seeks → jump the same stream's playhead. Ignore the echo from our own
  // onTimeUpdate feedback so playback isn't re-seeked every ~250ms.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || seekTs == null || rows.length === 0) return;
    if (seekTs === lastEmitted.current) return;
    try {
      video.currentTime = wallToMedia(seekTs);
      void video.play().catch(() => {});
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekTs]);

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (!video || !onTimeUpdate || rows.length === 0) return;
    const ts = mediaToWall(video.currentTime);
    lastEmitted.current = ts;
    onTimeUpdate(ts);
  };

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
      {segments.length === 0 ? (
        <div className="flex h-full items-center justify-center text-sm text-white/40">
          이 구간에 녹화된 영상이 없습니다
        </div>
      ) : (
        <>
          <video
            ref={videoRef}
            controls
            autoPlay
            muted
            playsInline
            onTimeUpdate={handleTimeUpdate}
            className="h-full w-full object-contain"
          />
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-center text-sm text-white/70">
              영상을 재생할 수 없습니다 (지원되지 않는 코덱이거나 세그먼트 손상)
            </div>
          )}
        </>
      )}
    </div>
  );
}
