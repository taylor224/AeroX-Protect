import { useEffect, useRef, useState } from 'react';

import { segmentDataUrl } from '@/pages/playback/playback.api';
import type { Segment } from '@/types/p2';

/**
 * VOD player by segment-chaining (PLAN P2 §7.2-B). Plays the segment containing the
 * seek time via MP4 range, advances to the next on 'ended'. Works with plain <video>
 * (no MSE/HLS) and is range-served + JWT-guarded by the backend.
 */
export function Player({
  segments,
  seekTs,
  onTimeUpdate,
}: {
  segments: Segment[];
  seekTs: number | null;
  onTimeUpdate?: (ts: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [index, setIndex] = useState<number | null>(null);
  const pendingOffset = useRef(0); // seconds to seek into the resolved segment once it loads
  const loadedId = useRef<string | null>(null); // segment currently loaded in the <video>
  const lastEmitted = useRef<number | null>(null); // playhead we pushed up from timeupdate

  // resolve a seek time → the segment to play, and where in it. Re-runs when `segments`
  // changes too, so a click that lands before the segments finish loading isn't dropped.
  useEffect(() => {
    if (seekTs == null || segments.length === 0) {
      setIndex(null);
      return;
    }
    // ignore the seekTs change we caused ourselves via onTimeUpdate during playback — re-seeking
    // to the live position every ~250ms would stutter. Only real (click) seeks get past here.
    if (seekTs === lastEmitted.current) return;
    // segment containing the click; else the nearest one to the RIGHT (next recording);
    // else (click past the end) the last one. Segments are ordered by start_ts ascending.
    let i = segments.findIndex((s) => s.start_ts <= seekTs && s.end_ts > seekTs);
    if (i < 0) i = segments.findIndex((s) => s.start_ts >= seekTs);
    if (i < 0) i = segments.length - 1;
    const seg = segments[i];
    // offset = where in the segment the click fell (0 when we snapped right to a later segment)
    pendingOffset.current = Math.max(0, Math.min((seekTs - seg.start_ts) / 1000, seg.duration_ms / 1000 - 0.1));
    setIndex(i);
    // if that exact segment is already mounted, onLoadedMetadata won't fire again → seek now
    const video = videoRef.current;
    if (video && loadedId.current === seg.id) {
      try {
        video.currentTime = pendingOffset.current;
      } catch {
        /* ignore */
      }
      void video.play().catch(() => {});
    }
  }, [seekTs, segments]);

  const current = index != null ? segments[index] : null;

  // fires on the (correctly-mounted) <video> element whenever a new segment's metadata loads —
  // apply the pending seek offset there so it lands on the right element, not a stale ref
  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (!video || !current) return;
    loadedId.current = current.id;
    try {
      video.currentTime = pendingOffset.current;
    } catch {
      /* ignore */
    }
    void video.play().catch(() => {});
  };

  const handleEnded = () => {
    if (index == null) return;
    const next = index + 1;
    if (next < segments.length) {
      pendingOffset.current = 0; // continue the next clip from its start
      setIndex(next);
    }
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (video && current && onTimeUpdate) {
      const ts = current.start_ts + video.currentTime * 1000;
      lastEmitted.current = ts; // remember it so the resolve effect can ignore this feedback
      onTimeUpdate(ts);
    }
  };

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
      {current ? (
        <video
          ref={videoRef}
          key={current.id}
          src={segmentDataUrl(current.id)}
          controls
          autoPlay
          playsInline
          onLoadedMetadata={handleLoadedMetadata}
          onEnded={handleEnded}
          onTimeUpdate={handleTimeUpdate}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-white/40">
          타임라인에서 재생 위치를 선택하세요
        </div>
      )}
    </div>
  );
}
