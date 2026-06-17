import { useEffect, useRef, useState } from 'react';

import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { eventColor } from '@/pages/events/eventMeta';
import type { EventMarker } from '@/types/p3';
import type { Bookmark } from '@/types/p6';

const MIN_SPAN = 10_000; // 10s zoom floor

/**
 * Event scrub bar (PLAN §7.1): recording coverage filled, event markers as colored ticks,
 * bookmarks as flag ticks. Now zoomable + pannable: wheel zooms (centered on cursor), drag
 * pans, click seeks, "fit" resets to the selected range.
 */
export function EventTimeline({
  from,
  to,
  coverage,
  markers,
  bookmarks = [],
  playhead,
  selectedId,
  onSeek,
  onPickEvent,
}: {
  from: number;
  to: number;
  coverage: { start: number; end: number }[];
  markers: EventMarker[];
  bookmarks?: Bookmark[];
  playhead: number;
  selectedId?: string | null;
  onSeek: (ts: number) => void;
  onPickEvent: (eventId: string, ts: number) => void;
}) {
  const { locale } = useTranslation();
  const trackRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ from, to });
  const drag = useRef<{ x: number; from: number; to: number; moved: boolean } | null>(null);

  // reset the viewport whenever the data window (selected range) changes
  useEffect(() => setView({ from, to }), [from, to]);

  const vFrom = view.from;
  const vTo = view.to;
  const span = Math.max(1, vTo - vFrom);
  const pct = (ts: number) => ((ts - vFrom) / span) * 100;
  const zoomed = vFrom > from || vTo < to;

  const clamp = (f: number, t: number) => {
    let s = Math.max(MIN_SPAN, Math.min(to - from, t - f));
    if (f < from) f = from;
    if (f + s > to) f = to - s;
    if (f < from) f = from;
    return { from: f, to: f + s };
  };

  // wheel zoom (non-passive so we can preventDefault page scroll). A ref holds the latest
  // closure so the listener is attached once but always sees current view state.
  const wheelFn = useRef<(e: WheelEvent) => void>(() => {});
  wheelFn.current = (e: WheelEvent) => {
    const track = trackRef.current;
    if (!track) return;
    e.preventDefault();
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const pivot = vFrom + ratio * span;
    const factor = e.deltaY > 0 ? 1.25 : 1 / 1.25; // down = zoom out
    const newSpan = Math.max(MIN_SPAN, Math.min(to - from, span * factor));
    setView(clamp(pivot - ratio * newSpan, pivot - ratio * newSpan + newSpan));
  };
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const h = (e: WheelEvent) => wheelFn.current(e);
    el.addEventListener('wheel', h, { passive: false });
    return () => el.removeEventListener('wheel', h);
  }, []);

  const onDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, from: vFrom, to: vTo, moved: false };
    const move = (ev: MouseEvent) => {
      const d = drag.current;
      const track = trackRef.current;
      if (!d || !track) return;
      const dx = ev.clientX - d.x;
      if (Math.abs(dx) > 3) d.moved = true;
      const deltaTs = -(dx / track.getBoundingClientRect().width) * (d.to - d.from);
      setView(clamp(d.from + deltaTs, d.to + deltaTs));
    };
    const up = (ev: MouseEvent) => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      const d = drag.current;
      drag.current = null;
      const track = trackRef.current;
      if (d && !d.moved && track) {
        const rect = track.getBoundingClientRect();
        const ratio = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
        onSeek(Math.round(vFrom + ratio * span));
      }
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  const ticks = Array.from({ length: 7 }, (_, i) => vFrom + (span * i) / 6);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px] text-white/50">
        <span>{formatDateTime(vFrom, locale)}</span>
        <span className="flex items-center gap-2">
          <span className="text-white/30">{intl_hint(locale)}</span>
          {zoomed && (
            <button onClick={() => setView({ from, to })} className="rounded bg-white/10 px-1.5 py-0.5 hover:bg-white/20">
              fit
            </button>
          )}
        </span>
        <span>{formatDateTime(vTo, locale)}</span>
      </div>
      <div
        ref={trackRef}
        onMouseDown={onDown}
        className="relative h-16 w-full cursor-ew-resize select-none overflow-hidden rounded bg-white/5"
      >
        {coverage.map((r, i) => {
          const l = pct(r.start);
          const w = pct(r.end) - l;
          if (l > 100 || l + w < 0) return null;
          return (
            <div key={`c${i}`} className="absolute top-0 h-full bg-primary/25"
              style={{ left: `${Math.max(0, l)}%`, width: `${Math.max(0.3, Math.min(100, l + w) - Math.max(0, l))}%` }} />
          );
        })}
        {markers.map((m) => {
          const left = pct(m.ts);
          if (left < 0 || left > 100) return null;
          const active = selectedId === m.event_id;
          return (
            <button
              key={m.event_id}
              title={`${m.type} · ${formatDateTime(m.ts, locale)}`}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); onPickEvent(m.event_id, m.ts); }}
              className="absolute top-1 z-10 -translate-x-1/2"
              style={{ left: `${left}%` }}
            >
              <span className="block rounded-sm" style={{
                width: active ? 7 : 4, height: active ? 50 : 40, background: eventColor(m.type),
                boxShadow: active ? '0 0 0 2px rgba(255,255,255,0.8)' : 'none',
              }} />
            </button>
          );
        })}
        {bookmarks.map((b) => {
          const left = pct(b.start_ts);
          if (left < 0 || left > 100) return null;
          return (
            <button
              key={b.id}
              title={`★ ${b.label} · ${formatDateTime(b.start_ts, locale)}`}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); onSeek(b.start_ts); }}
              className="absolute bottom-0 z-10 -translate-x-1/2"
              style={{ left: `${left}%` }}
            >
              <span className="block h-3 w-3 rotate-45 rounded-[2px]"
                style={{ background: b.color ?? '#3E6AE1', boxShadow: '0 0 0 1.5px rgba(0,0,0,0.35)' }} />
            </button>
          );
        })}
        {playhead >= vFrom && playhead <= vTo && (
          <div className="pointer-events-none absolute top-0 z-20 h-full w-0.5 bg-white" style={{ left: `${pct(playhead)}%` }} />
        )}
      </div>
      <div className="flex justify-between text-[10px] text-white/40">
        {ticks.map((t, i) => (
          <span key={i}>{formatDateTime(t, locale).split(' ').slice(-1)[0]}</span>
        ))}
      </div>
    </div>
  );
}

function intl_hint(locale: string): string {
  return locale === 'ko' ? '휠=확대 · 드래그=이동' : 'wheel=zoom · drag=pan';
}
