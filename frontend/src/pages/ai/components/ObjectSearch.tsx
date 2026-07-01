import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useIntl } from 'react-intl';

import { Card } from '@/components/ui/card';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { detectionSnapshotUrl, getDetectionOverlay, searchDetections } from '@/pages/ai/ai.api';
import { DetectionOverlay } from '@/pages/ai/components/DetectionOverlay';
import { Player } from '@/pages/playback/components/Player';
import { getSegments } from '@/pages/playback/playback.api';
import { DETECTION_LABELS, type DetectionGroup } from '@/types/p4';

const HOUR = 3600_000;
const ZOOMS = [
  { key: '1h', ms: HOUR },
  { key: '24h', ms: 24 * HOUR },
  { key: '7d', ms: 7 * 24 * HOUR },
];

export function ObjectSearch({ cameraUuid, cameraId }: { cameraUuid: string; cameraId?: string }) {
  const intl = useIntl();
  const { locale } = useTranslation();
  const [windowMs, setWindowMs] = useState(24 * HOUR);
  const [anchorTo] = useState(() => Date.now());
  const [labels, setLabels] = useState<string[]>([]);
  const [minConf, setMinConf] = useState(40);
  const [selected, setSelected] = useState<DetectionGroup | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);

  const from = anchorTo - windowMs;
  const to = anchorTo;

  const searchQuery = useQuery({
    queryKey: ['det-search', cameraId, from, to, labels, minConf],
    queryFn: () => searchDetections({ cameraId, labels, start: from, end: to, minConfidence: minConf, group: 'clip' }),
    enabled: !!cameraId,
  });

  const segmentsQuery = useQuery({
    queryKey: ['det-segments', cameraUuid, selected?.rep_detection_id],
    queryFn: () => getSegments(cameraUuid, selected!.start_ts, selected!.end_ts),
    enabled: !!selected && !!cameraUuid,
  });

  const overlayQuery = useQuery({
    queryKey: ['det-overlay', cameraUuid, selected?.rep_detection_id],
    queryFn: () => getDetectionOverlay(cameraUuid, selected!.start_ts, selected!.end_ts),
    enabled: !!selected && !!cameraUuid,
  });

  const items = useMemo(() => searchQuery.data?.items ?? [], [searchQuery.data]);
  const segments = useMemo(() => segmentsQuery.data ?? [], [segmentsQuery.data]);

  const toggleLabel = (l: string) =>
    setLabels((prev) => (prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l]));

  const pick = (g: DetectionGroup) => {
    setSelected(g);
    setPlayhead(g.start_ts);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded border border-border p-0.5">
          {ZOOMS.map((z) => (
            <button
              key={z.key}
              onClick={() => setWindowMs(z.ms)}
              className={`rounded px-2.5 py-1 text-sm transition-colors ${
                windowMs === z.ms ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'
              }`}
            >
              {z.key}
            </button>
          ))}
        </div>
        {DETECTION_LABELS.map((l) => (
          <button
            key={l}
            onClick={() => toggleLabel(l)}
            className={`rounded-full border px-2.5 py-1 text-xs transition ${
              labels.includes(l) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'
            }`}
          >
            {intl.formatMessage({ id: `ai.label.${l}`, defaultMessage: l })}
          </button>
        ))}
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          {intl.formatMessage({ id: 'ai.min_conf' })}
          <input type="range" min={0} max={100} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} />
          <span className="tabular-nums">{minConf}%</span>
        </label>
      </div>

      {selected && (
        <div className="relative mx-auto max-w-3xl">
          <Player
            cameraUuid={cameraUuid}
            from={selected.start_ts}
            to={selected.end_ts}
            segments={segments}
            seekTs={playhead}
            onTimeUpdate={setPlayhead}
          />
          {overlayQuery.data && <DetectionOverlay tracks={overlayQuery.data.tracks} playhead={playhead ?? from} />}
        </div>
      )}

      {searchQuery.isLoading ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'common.loading' })}</Card>
      ) : items.length === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'ai.no_results' })}</Card>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((g) => (
            <button
              key={g.rep_detection_id}
              onClick={() => pick(g)}
              className={`overflow-hidden rounded-xl border text-left transition ${
                selected?.rep_detection_id === g.rep_detection_id ? 'border-primary' : 'border-border hover:border-border-strong'
              }`}
            >
              <div className="relative aspect-[2/1] bg-black">
                <img
                  src={detectionSnapshotUrl(g.rep_detection_id)}
                  alt={g.labels.join(',')}
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
                />
                <div className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
                  {g.labels.join(', ')}
                </div>
                <div className="absolute right-1.5 top-1.5 rounded bg-primary/80 px-1.5 py-0.5 text-[11px] text-white">
                  {g.top_confidence}%
                </div>
              </div>
              <div className="flex items-center justify-between px-2 py-1.5 text-[11px] text-muted-foreground">
                <span>{formatDateTime(g.start_ts, locale)}</span>
                <span>×{g.count}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
