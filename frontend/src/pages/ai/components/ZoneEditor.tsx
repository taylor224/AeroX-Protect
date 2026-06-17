import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { createZone, deleteZone, listZones } from '@/pages/ai/ai.api';
import { frameUrl } from '@/pages/playback/playback.api';
import type { ZoneKind } from '@/types/p4';

const ZONE_COLORS = ['#3E6AE1', '#22C55E', '#F59E0B', '#EF4444', '#A855F7'];

export function ZoneEditor({ cameraUuid, canEdit }: { cameraUuid: string; canEdit: boolean }) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const boxRef = useRef<HTMLDivElement>(null);
  const [pts, setPts] = useState<[number, number][]>([]);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<ZoneKind>('include');
  const [anchor] = useState(() => Date.now() - 5000);

  const zonesQuery = useQuery({
    queryKey: ['zones', cameraUuid],
    queryFn: () => listZones(cameraUuid),
    enabled: !!cameraUuid,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['zones', cameraUuid] });
  const saveMut = useMutation({
    mutationFn: () => createZone(cameraUuid, { name: name || 'zone', kind, polygon: pts }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'ai.zone_saved' }));
      setPts([]);
      setName('');
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteZone(id), onSuccess: invalidate });

  const addPoint = (e: React.MouseEvent) => {
    if (!canEdit) return;
    const rect = boxRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    setPts((p) => [...p, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  };

  const toPoints = (poly: [number, number][]) => poly.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');
  const zones = zonesQuery.data ?? [];

  return (
    <Card className="space-y-3 bg-canvas p-4">
      <div
        ref={boxRef}
        onClick={addPoint}
        className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg bg-black"
      >
        <img
          src={frameUrl(cameraUuid, anchor)}
          alt=""
          className="h-full w-full object-contain opacity-80"
          onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
        />
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {zones.map((z, i) => (
            <polygon
              key={z.id}
              points={toPoints(z.polygon)}
              fill={`${z.color || ZONE_COLORS[i % ZONE_COLORS.length]}22`}
              stroke={z.color || ZONE_COLORS[i % ZONE_COLORS.length]}
              strokeWidth={0.4}
              strokeDasharray={z.kind === 'ignore' ? '2 1' : undefined}
            />
          ))}
          {pts.length > 0 && (
            <polygon points={toPoints(pts)} fill="#3E6AE133" stroke="#3E6AE1" strokeWidth={0.5} />
          )}
          {pts.map(([x, y], i) => (
            <circle key={i} cx={x * 100} cy={y * 100} r={0.7} fill="#3E6AE1" />
          ))}
        </svg>
      </div>

      {canEdit && (
        <div className="flex flex-wrap items-center gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={intl.formatMessage({ id: 'ai.zone_name' })} className="w-44" />
          <div className="flex items-center gap-1 rounded border border-border p-0.5">
            {(['include', 'ignore'] as ZoneKind[]).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={`rounded px-2.5 py-1 text-sm ${kind === k ? 'bg-secondary text-foreground' : 'text-muted-foreground'}`}
              >
                {intl.formatMessage({ id: `ai.zone_kind.${k}` })}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setPts([])} disabled={!pts.length}>
            {intl.formatMessage({ id: 'ai.zone_clear' })}
          </Button>
          <Button size="sm" onClick={() => saveMut.mutate()} disabled={pts.length < 3 || saveMut.isPending}>
            {intl.formatMessage({ id: 'common.save' })}
          </Button>
          <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'ai.zone_hint' })}</span>
        </div>
      )}

      <div className="space-y-1">
        {zones.map((z, i) => (
          <div key={z.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
            <span className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-sm" style={{ background: z.color || ZONE_COLORS[i % ZONE_COLORS.length] }} />
              {z.name} · {intl.formatMessage({ id: `ai.zone_kind.${z.kind}` })}
            </span>
            {canEdit && (
              <Button variant="ghost" size="icon" onClick={async () => {
                if (await confirm({
                  title: intl.formatMessage({ id: 'confirm.delete.title' }),
                  description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: z.name }),
                  confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                  destructive: true,
                }))
                  delMut.mutate(z.id);
              }}>
                <Trash2 className="h-4 w-4 text-red-400" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
