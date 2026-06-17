import { useRef } from 'react';

import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import type { TimeRange } from '@/types/p2';

/** Scrub bar (PLAN P2 §7.1): dark track, recording ranges filled, accent playhead. */
export function Timeline({
  from,
  to,
  ranges,
  playhead,
  onSeek,
}: {
  from: number;
  to: number;
  ranges: TimeRange[];
  playhead: number;
  onSeek: (ts: number) => void;
}) {
  const { locale } = useTranslation();
  const trackRef = useRef<HTMLDivElement>(null);
  const total = Math.max(1, to - from);

  const pct = (ts: number) => ((ts - from) / total) * 100;

  const handleClick = (e: React.MouseEvent) => {
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(Math.round(from + ratio * total));
  };

  // hour/段 ticks (~6 evenly spaced labels)
  const ticks = Array.from({ length: 7 }, (_, i) => from + (total * i) / 6);

  return (
    <div className="space-y-1">
      <div
        ref={trackRef}
        onClick={handleClick}
        className="relative h-12 w-full cursor-pointer overflow-hidden rounded bg-white/5"
      >
        {ranges.map((r, i) => (
          <div
            key={i}
            className="absolute top-0 h-full bg-primary/35"
            style={{ left: `${pct(r.start)}%`, width: `${Math.max(0.3, pct(r.end) - pct(r.start))}%` }}
          />
        ))}
        {playhead >= from && playhead <= to && (
          <div className="absolute top-0 h-full w-0.5 bg-[#3E6AE1]" style={{ left: `${pct(playhead)}%` }} />
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
