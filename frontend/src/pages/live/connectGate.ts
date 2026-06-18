/**
 * Global stagger for live-stream connection *starts*.
 *
 * A camera-wall page mounts N tiles at once; without throttling they'd all open their go2rtc
 * connection (and trigger N H.265→H.264 transcode cold-starts) in the same instant — the spike
 * that made the dashboard time out, fall back, and watchdog-storm. This grants a start slot at
 * most every STAGGER_MS so connections begin a beat apart (tiles pop in progressively, like
 * Frigate). It also spreads out the thundering-herd reconnect after a go2rtc restart.
 *
 * It throttles the *rate* of new connects, not the *number* of concurrent streams — a wall is
 * meant to show every tile, so there is nothing to release and no risk of deadlock. Once the
 * burst drains and wall-clock passes the last slot, the next caller starts immediately.
 */
const STAGGER_MS = 200;
let nextSlot = 0;

/** Resolve when this caller may begin connecting. Await it, then start the transport. */
export function acquireStartSlot(): Promise<void> {
  const now = Date.now();
  const at = Math.max(now, nextSlot);
  nextSlot = at + STAGGER_MS;
  const wait = at - now;
  return wait <= 0 ? Promise.resolve() : new Promise((resolve) => window.setTimeout(resolve, wait));
}
