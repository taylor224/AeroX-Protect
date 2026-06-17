import type { OverlayShape } from '@/types/p3';

/**
 * Region overlay (PLAN §7.1). Normalized 0–1 vendor coordinates → SVG polygons drawn
 * over the player. viewBox 0 0 1 1 + preserveAspectRatio=none maps coords to the box.
 */
export function MotionOverlay({ shapes }: { shapes: OverlayShape[] }) {
  if (!shapes?.length) return null;
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
    >
      {shapes.map((s, i) =>
        s.pts.length >= 2 ? (
          <polygon
            key={i}
            points={s.pts.map(([x, y]) => `${x},${y}`).join(' ')}
            fill="rgba(62,106,225,0.18)"
            stroke="#3E6AE1"
            strokeWidth={0.004}
            vectorEffect="non-scaling-stroke"
          />
        ) : null,
      )}
    </svg>
  );
}
