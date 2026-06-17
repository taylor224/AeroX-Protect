import { useQuery } from '@tanstack/react-query';
import { AudioLines } from 'lucide-react';
import { useIntl } from 'react-intl';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { audioLabels, listAudioDetections } from '@/pages/ai/audio.api';

const LOUD = new Set(['glass_break', 'scream', 'gunshot', 'alarm']);

/** A4 — recent classified audio events for the selected camera (glass break / scream /
 *  alarm …). The detector worker classifies windows; high-score windows also raise events. */
export function AudioDetections({ cameraUuid }: { cameraUuid: string }) {
  const intl = useIntl();
  const detQuery = useQuery({
    queryKey: ['audio-detections', cameraUuid],
    queryFn: () => listAudioDetections(cameraUuid),
    enabled: !!cameraUuid,
    refetchInterval: 5000,
  });
  const metaQuery = useQuery({ queryKey: ['audio-labels'], queryFn: audioLabels });

  const items = detQuery.data ?? [];

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <AudioLines className="h-4 w-4" />
          {intl.formatMessage({ id: 'audio.recent' })}
        </h2>
        {metaQuery.data && (
          <Badge variant={metaQuery.data.backend === 'stub' ? 'muted' : 'success'}>
            {intl.formatMessage({ id: 'audio.backend' }, { backend: metaQuery.data.backend })}
          </Badge>
        )}
      </div>

      <div className="max-h-[28rem] space-y-1 overflow-auto">
        {items.map((d) => (
          <div key={d.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
            <span className="flex items-center gap-2">
              <Badge variant={LOUD.has(d.label) ? 'danger' : 'muted'}>{d.label}</Badge>
              {d.event_id && <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'audio.event_raised' })}</span>}
            </span>
            <span className="flex items-center gap-3 text-muted-foreground">
              <span className="tabular-nums">{d.score}</span>
              <span className="text-xs">{d.ts ? new Date(d.ts).toLocaleTimeString() : '—'}</span>
            </span>
          </div>
        ))}
        {items.length === 0 && (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {intl.formatMessage({ id: 'audio.empty' })}
          </p>
        )}
      </div>
    </Card>
  );
}
