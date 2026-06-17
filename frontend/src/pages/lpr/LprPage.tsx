import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ScanLine, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useFeatureFlag } from '@/lib/featureFlags';
import { listCameras } from '@/pages/cameras/camera.api';
import {
  createWatchlistEntry,
  deleteWatchlistEntry,
  listCameraPlates,
  listWatchlist,
  searchPlates,
  type PlateRead,
} from '@/pages/lpr/lpr.api';

export function LprPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('lpr');
  const canManage = hasPermission('lpr', 'manage');

  const [cameraUuid, setCameraUuid] = useState('');
  const [query, setQuery] = useState('');
  const [newPlate, setNewPlate] = useState('');
  const [newKind, setNewKind] = useState<'allow' | 'deny'>('deny');
  const [newLabel, setNewLabel] = useState('');

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];
  const selectedUuid = cameraUuid || cameras[0]?.uuid || '';

  const readsQuery = useQuery({
    queryKey: ['plate-reads', selectedUuid],
    queryFn: () => listCameraPlates(selectedUuid),
    enabled: enabled && !!selectedUuid && !query,
    refetchInterval: enabled ? 5000 : false,
  });
  const searchQuery = useQuery({
    queryKey: ['plate-search', query],
    queryFn: () => searchPlates(query),
    enabled: enabled && query.trim().length > 0,
  });
  const listQuery = useQuery({ queryKey: ['plate-watchlist'], queryFn: listWatchlist, enabled });

  const addMut = useMutation({
    mutationFn: () => createWatchlistEntry({ plate_text: newPlate.trim(), kind: newKind, label: newLabel.trim() || undefined }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'lpr.added' }));
      setNewPlate('');
      setNewLabel('');
      queryClient.invalidateQueries({ queryKey: ['plate-watchlist'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'lpr.add_failed' })),
  });
  const delMut = useMutation({
    mutationFn: (id: string) => deleteWatchlistEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['plate-watchlist'] }),
  });

  if (!enabled) {
    return (
      <Card className="p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'lpr.disabled' })}
      </Card>
    );
  }

  const reads = query ? (searchQuery.data ?? []) : (readsQuery.data ?? []);

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
        <ScanLine className="h-5 w-5" />
        {intl.formatMessage({ id: 'menu.lpr' })}
      </h1>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* reads */}
        <Card className="space-y-3 p-4 lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="h-9 rounded border border-input bg-background px-2 text-sm"
              value={selectedUuid}
              onChange={(e) => setCameraUuid(e.target.value)}
            >
              {cameras.map((c) => (
                <option key={c.uuid} value={c.uuid}>{c.name}</option>
              ))}
            </select>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={intl.formatMessage({ id: 'lpr.search_ph' })}
              className="h-9 w-56"
            />
          </div>

          <div className="max-h-[30rem] space-y-1 overflow-auto">
            {reads.map((r: PlateRead) => (
              <div key={r.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
                <span className="flex items-center gap-2">
                  <span className="font-mono font-medium tracking-wider">{r.plate_text}</span>
                  {r.list_kind === 'deny' && <Badge variant="danger">{intl.formatMessage({ id: 'lpr.deny' })}</Badge>}
                  {r.list_kind === 'allow' && <Badge variant="success">{intl.formatMessage({ id: 'lpr.allow' })}</Badge>}
                </span>
                <span className="flex items-center gap-3 text-muted-foreground">
                  <span className="tabular-nums">{r.confidence}</span>
                  <span className="text-xs">{r.ts ? new Date(r.ts).toLocaleString() : '—'}</span>
                </span>
              </div>
            ))}
            {reads.length === 0 && (
              <p className="py-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'lpr.no_reads' })}</p>
            )}
          </div>
        </Card>

        {/* watchlist */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'lpr.watchlist' })}</h2>
          {canManage && (
            <div className="space-y-2">
              <Input value={newPlate} onChange={(e) => setNewPlate(e.target.value)}
                placeholder={intl.formatMessage({ id: 'lpr.plate_ph' })} className="font-mono" />
              <div className="flex gap-2">
                <select className="h-9 flex-1 rounded border border-input bg-background px-2 text-sm"
                  value={newKind} onChange={(e) => setNewKind(e.target.value as 'allow' | 'deny')}>
                  <option value="deny">{intl.formatMessage({ id: 'lpr.deny' })}</option>
                  <option value="allow">{intl.formatMessage({ id: 'lpr.allow' })}</option>
                </select>
                <Input value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
                  placeholder={intl.formatMessage({ id: 'lpr.label_ph' })} className="flex-1" />
              </div>
              <Button size="sm" className="w-full" disabled={!newPlate.trim() || addMut.isPending}
                onClick={() => addMut.mutate()}>
                {intl.formatMessage({ id: 'lpr.add' })}
              </Button>
            </div>
          )}
          <div className="max-h-80 space-y-1 overflow-auto">
            {(listQuery.data ?? []).map((e) => (
              <div key={e.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
                <span className="flex items-center gap-2">
                  <Badge variant={e.kind === 'deny' ? 'danger' : 'success'}>{e.kind}</Badge>
                  <span className="font-mono">{e.plate_text}</span>
                  {e.label && <span className="text-xs text-muted-foreground">{e.label}</span>}
                </span>
                {canManage && (
                  <Button variant="ghost" size="icon" onClick={async () => {
                    if (await confirm({
                      title: intl.formatMessage({ id: 'confirm.delete.title' }),
                      description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: e.plate_text }),
                      confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                      destructive: true,
                    }))
                      delMut.mutate(e.id);
                  }} aria-label="delete">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {(listQuery.data ?? []).length === 0 && (
              <p className="py-6 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'lpr.no_watchlist' })}</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
