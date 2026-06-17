import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightLeft, Hexagon, Trash2 } from 'lucide-react';
import { useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  createCountingLine,
  deleteCountingLine,
  getCountingAnalytics,
  listCountingLines,
} from '@/pages/ai/counting.api';
import { frameUrl } from '@/pages/playback/playback.api';

const DAY = 86_400_000;
const pct = (poly: [number, number][]) => poly.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');

export function CountingEditor({ cameraUuid, canEdit }: { cameraUuid: string; canEdit: boolean }) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const boxRef = useRef<HTMLDivElement>(null);
  const [pts, setPts] = useState<[number, number][]>([]);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'line' | 'region'>('line');
  const [loiter, setLoiter] = useState('');
  const [anchor] = useState(() => Date.now() - 5000);

  const linesQuery = useQuery({ queryKey: ['counting', cameraUuid], queryFn: () => listCountingLines(cameraUuid), enabled: !!cameraUuid });
  const statsQuery = useQuery({
    queryKey: ['counting-stats', cameraUuid],
    queryFn: () => getCountingAnalytics(cameraUuid, Date.now() - DAY, Date.now()),
    enabled: !!cameraUuid,
    refetchInterval: 10_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['counting', cameraUuid] });
    void queryClient.invalidateQueries({ queryKey: ['counting-stats', cameraUuid] });
  };
  const saveMut = useMutation({
    mutationFn: () =>
      createCountingLine(cameraUuid, {
        name: name.trim() || kind,
        kind,
        geometry: pts,
        loiter_threshold_s: kind === 'region' && loiter ? Number(loiter) : undefined,
      }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'count.saved' }));
      setPts([]);
      setName('');
      setLoiter('');
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteCountingLine(id), onSuccess: invalidate });

  const addPoint = (e: React.MouseEvent) => {
    if (!canEdit || (kind === 'line' && pts.length >= 2)) return;
    const rect = boxRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    setPts((p) => [...p, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  };

  const lines = linesQuery.data ?? [];
  const stats = statsQuery.data ?? [];
  const agg = (lineId: string) => {
    let i = 0, o = 0, occ = 0;
    for (const s of stats) if (s.line_id === lineId) { i += s.in_count; o += s.out_count; occ = Math.max(occ, s.occupancy); }
    return { i, o, occ };
  };
  const minPts = kind === 'line' ? 2 : 3;

  return (
    <div className="space-y-3">
      <Card className="space-y-3 bg-canvas p-4">
        <div ref={boxRef} onClick={addPoint} className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg bg-black">
          <img src={frameUrl(cameraUuid, anchor)} alt="" className="h-full w-full object-contain opacity-80"
            onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')} />
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
            {lines.map((l) =>
              l.kind === 'line' ? (
                <polyline key={l.id} points={pct(l.geometry)} fill="none" stroke="#3E6AE1" strokeWidth={0.6} />
              ) : (
                <polygon key={l.id} points={pct(l.geometry)} fill="#3E6AE122" stroke="#3E6AE1" strokeWidth={0.4} />
              ),
            )}
            {pts.length > 0 &&
              (kind === 'line' ? (
                <polyline points={pct(pts)} fill="none" stroke="#F59E0B" strokeWidth={0.6} />
              ) : (
                <polygon points={pct(pts)} fill="#F59E0B33" stroke="#F59E0B" strokeWidth={0.5} />
              ))}
            {pts.map(([x, y], i) => <circle key={i} cx={x * 100} cy={y * 100} r={0.8} fill="#F59E0B" />)}
          </svg>
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded border border-border p-0.5">
              <button onClick={() => { setKind('line'); setPts([]); }}
                className={`flex items-center gap-1 rounded px-2.5 py-1 text-sm ${kind === 'line' ? 'bg-secondary text-foreground' : 'text-muted-foreground'}`}>
                <ArrowRightLeft className="h-3.5 w-3.5" />{intl.formatMessage({ id: 'count.line' })}
              </button>
              <button onClick={() => { setKind('region'); setPts([]); }}
                className={`flex items-center gap-1 rounded px-2.5 py-1 text-sm ${kind === 'region' ? 'bg-secondary text-foreground' : 'text-muted-foreground'}`}>
                <Hexagon className="h-3.5 w-3.5" />{intl.formatMessage({ id: 'count.region' })}
              </button>
            </div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={intl.formatMessage({ id: 'count.name' })} className="w-36" />
            {kind === 'region' && (
              <Input value={loiter} onChange={(e) => setLoiter(e.target.value)} type="number" placeholder={intl.formatMessage({ id: 'count.loiter' })} className="w-40" />
            )}
            <Button variant="ghost" size="sm" onClick={() => setPts([])} disabled={!pts.length}>{intl.formatMessage({ id: 'count.clear' })}</Button>
            <Button size="sm" onClick={() => saveMut.mutate()} disabled={pts.length < minPts || saveMut.isPending}>{intl.formatMessage({ id: 'common.save' })}</Button>
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: kind === 'line' ? 'count.hint_line' : 'count.hint_region' })}</span>
          </div>
        )}
      </Card>

      <div className="space-y-1.5">
        {lines.map((l) => {
          const a = agg(l.id);
          return (
            <div key={l.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
              <span className="flex items-center gap-2">
                {l.kind === 'line' ? <ArrowRightLeft className="h-4 w-4 text-primary" /> : <Hexagon className="h-4 w-4 text-primary" />}
                <span className="font-medium text-foreground">{l.name}</span>
                {l.loiter_threshold_s ? <span className="text-xs text-amber-600">배회 {l.loiter_threshold_s}s</span> : null}
              </span>
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                {l.kind === 'line' ? (
                  <span className="tabular-nums">↑{a.i} · ↓{a.o}</span>
                ) : (
                  <span className="tabular-nums">{intl.formatMessage({ id: 'count.occupancy' })} {a.occ}</span>
                )}
                {canEdit && (
                  <Button variant="ghost" size="icon" onClick={async () => {
                    if (await confirm({
                      title: intl.formatMessage({ id: 'confirm.delete.title' }),
                      description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: l.name }),
                      confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                      destructive: true,
                    }))
                      delMut.mutate(l.id);
                  }} aria-label="delete">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </span>
            </div>
          );
        })}
        {lines.length === 0 && <p className="py-4 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'count.empty' })}</p>}
      </div>
    </div>
  );
}
