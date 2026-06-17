import { useMemo } from 'react';

import type { OverlayTrack } from '@/types/p4';

/**
 * Playback detection overlay (PLAN P4 §8.3). Normalized 0–1 track bboxes drawn over the
 * player; for the current playhead, each track shows its nearest sample (±2s). HTML boxes
 * scale to the video display box naturally (letterbox-safe with object-contain wrappers).
 */
export function DetectionOverlay({ tracks, playhead }: { tracks: OverlayTrack[]; playhead: number }) {
  const boxes = useMemo(() => {
    const out: { label: string; bbox: number[]; conf: number }[] = [];
    for (const t of tracks) {
      let best: { ts: number; bbox: number[]; conf: number } | null = null;
      let bestDt = 2000;
      for (const p of t.points) {
        const dt = Math.abs(p.ts - playhead);
        if (dt <= bestDt) {
          best = p;
          bestDt = dt;
        }
      }
      if (best) out.push({ label: t.label, bbox: best.bbox, conf: best.conf });
    }
    return out;
  }, [tracks, playhead]);

  if (!boxes.length) return null;
  return (
    <div className="pointer-events-none absolute inset-0">
      {boxes.map((b, i) => {
        const [x1, y1, x2, y2] = b.bbox;
        return (
          <div
            key={i}
            className="absolute border-[1.5px] border-[#3E6AE1]"
            style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}
          >
            <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-[#3E6AE1] px-1 text-[10px] text-white">
              {b.label} {b.conf}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
