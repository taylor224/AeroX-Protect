import { Loader2, VideoOff } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';
import { thumbnailUrl } from '@/pages/live/live.api';

/**
 * Shared camera thumbnail tile.
 *  - Online: shows the cached frame, with a spinner while it's still loading (so an
 *    in-flight tile never looks the same as a dead feed).
 *  - Offline: still shows the LAST saved frame (dimmed) with a struck-through camera badge
 *    so the operator sees both the scene and that the feed is currently down. If no cached
 *    frame is available, falls back to a centered offline icon.
 *
 * The backend `camera_health_check` beat refreshes each camera's cached JPEG every ~30s, but
 * an <img> with a fixed src loads exactly once and would show that first frame forever. So we
 * bump a cache-busting token on `refreshMs` to re-fetch the latest frame, AND clear the failed
 * state on each tick so a tile that came up gray (cold cache / a momentary frame miss) retries
 * and self-heals once a frame becomes available — instead of staying gray until a remount.
 */
export function CameraThumbnail({
  cameraUuid,
  status,
  className,
  iconClassName,
  refreshMs = 30000,
}: {
  cameraUuid: string;
  status?: string;
  className?: string;
  iconClassName?: string;
  refreshMs?: number;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);
  const offline = status !== undefined && status !== 'online';
  const icon = iconClassName ?? 'h-5 w-5';

  useEffect(() => {
    if (refreshMs <= 0) return;
    const id = window.setInterval(() => {
      setTick((t) => t + 1);
      setFailed(false); // retry a previously-failed load against the freshly-cached frame
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs]);

  // changing the query param forces the browser past the max-age=30 cache to the latest frame.
  // The old frame stays painted until the new one decodes (no flicker — we don't reset `loaded`).
  const src = `${thumbnailUrl(cameraUuid)}&_=${tick}`;

  return (
    <div className={cn('relative flex items-center justify-center overflow-hidden bg-black/80', className)}>
      {!failed && (
        <img
          src={src}
          alt=""
          loading="lazy"
          className={cn('absolute inset-0 h-full w-full object-cover transition-opacity',
            loaded ? 'opacity-100' : 'opacity-0', offline && 'opacity-40')}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}

      {/* online + still loading → spinner */}
      {!offline && !loaded && !failed && (
        <Loader2 className={cn('animate-spin text-white/40', icon)} aria-label="loading" />
      )}

      {/* offline → struck-through camera icon centered over the (dimmed) last frame */}
      {offline && (
        loaded && !failed ? (
          <span className="absolute inset-0 flex items-center justify-center">
            <VideoOff className={cn('text-white/90 drop-shadow', icon)} aria-label="disconnected" />
          </span>
        ) : (
          <VideoOff className={cn('text-white/30', icon)} aria-label="disconnected" />
        )
      )}
    </div>
  );
}
