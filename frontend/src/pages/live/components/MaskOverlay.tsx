import { useQuery } from '@tanstack/react-query';

import { useFeatureFlag } from '@/lib/featureFlags';
import { listMasks } from '@/pages/cameras/mask.api';

const toPoints = (poly: [number, number][]) => poly.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');

/** Renders enabled privacy masks as opaque polygons over live/playback (server_render mode). */
export function MaskOverlay({ cameraUuid }: { cameraUuid: string }) {
  const enabled = useFeatureFlag('privacy_masks');

  const { data } = useQuery({
    queryKey: ['masks', cameraUuid],
    queryFn: () => listMasks(cameraUuid),
    enabled,
    staleTime: 60_000,
  });
  const masks = (data ?? []).filter((m) => m.enabled);
  if (!enabled || masks.length === 0) return null;

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-10 h-full w-full"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
    >
      {masks.map((m) => (
        <polygon key={m.id} points={toPoints(m.polygon)} fill="black" />
      ))}
    </svg>
  );
}
