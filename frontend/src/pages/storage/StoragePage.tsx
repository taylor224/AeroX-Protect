import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HardDrive } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  discoverDisks,
  getPolicy,
  getStorageUsage,
  listDisks,
  registerDisk,
  updatePolicy,
  type CameraUsage,
} from '@/pages/storage/storage.api';
import type { DiscoverCandidate } from '@/types/p2';

const GB = 1024 ** 3;
const fmtBytes = (b: number) => (b >= GB ? `${(b / GB).toFixed(1)} GB` : `${(b / 1024 / 1024).toFixed(0)} MB`);

// P6 M4 — disk health surfacing
const HEALTH_DOT: Record<string, string> = { ok: 'bg-emerald-500', warning: 'bg-amber-500', critical: 'bg-red-500' };
const HEALTH_BAR: Record<string, string> = { ok: 'bg-primary', warning: 'bg-amber-500', critical: 'bg-red-500' };

export function StoragePage() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canManage = hasPermission('storage', 'manage');
  const canRetention = hasPermission('retention', 'manage');

  const disksQuery = useQuery({ queryKey: ['storage-disks'], queryFn: listDisks, refetchInterval: 15000 });
  const discoverQuery = useQuery({ queryKey: ['storage-discover'], queryFn: discoverDisks, enabled: canManage });

  const disks = disksQuery.data ?? [];
  const candidates = (discoverQuery.data ?? []).filter(
    (c) => !disks.some((d) => d.mount_path === c.mount_path),
  );

  const registerMut = useMutation({
    mutationFn: (c: DiscoverCandidate & { role: string }) =>
      registerDisk({ name: c.mount_path.split('/').pop() || c.mount_path, mount_path: c.mount_path, role: c.role, reserved_free_bytes: 2 * GB }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'storage.disk_added' }));
      void queryClient.invalidateQueries({ queryKey: ['storage-disks'] });
      void queryClient.invalidateQueries({ queryKey: ['storage-discover'] });
    },
  });

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.storage' })}</h1>

      {canManage && candidates.length > 0 && (
        <Card className="border-primary/30 bg-primary/[0.04]">
          <CardContent className="space-y-3 p-5">
            <p className="text-sm font-medium text-foreground">
              {intl.formatMessage({ id: 'storage.discovered' }, { count: candidates.length })}
            </p>
            <div className="space-y-2">
              {candidates.map((c) => (
                <div
                  key={c.mount_path}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-4 py-2.5"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    <HardDrive className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                    <span className="truncate text-sm text-foreground">{c.mount_path}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {fmtBytes(c.free_bytes)} / {fmtBytes(c.total_bytes)}
                    </span>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => registerMut.mutate({ ...c, role: 'record' })}>
                    {intl.formatMessage({ id: 'storage.add_record' })}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {disks.map((d) => (
          <Card key={d.id} className="space-y-5 p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium text-foreground">{d.name}</div>
                <div className="mt-1 truncate text-xs text-muted-foreground">{d.mount_path}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${HEALTH_DOT[d.health ?? 'ok']}`}
                  title={intl.formatMessage({ id: `storage.health.${d.health ?? 'ok'}` })}
                />
                <Badge variant={d.role === 'record' ? 'default' : 'muted'}>{d.role}</Badge>
              </div>
            </div>
            <div className="space-y-2.5">
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-secondary">
                <div className={`h-full rounded-full ${HEALTH_BAR[d.health ?? 'ok']}`} style={{ width: `${d.usage_percent}%` }} />
              </div>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{fmtBytes(d.used_bytes)} / {fmtBytes(d.total_bytes)}</span>
                <span className="font-medium text-foreground">{d.usage_percent}%</span>
              </div>
            </div>
          </Card>
        ))}
        {disks.length === 0 && (
          <Card className="p-10 text-center text-sm text-muted-foreground md:col-span-3">
            {intl.formatMessage({ id: 'storage.no_disks' })}
          </Card>
        )}
      </div>

      {canRetention && <RetentionSettings />}
    </div>
  );
}

// '10.2/30GB' — stored bytes vs the retention cap that applies (∞-less when uncapped)
const fmtUsage = (c: CameraUsage) => {
  const used = (c.used_bytes / GB).toFixed(1);
  return c.retention_max_bytes ? `${used}/${Math.round(c.retention_max_bytes / GB)}GB` : `${used}GB`;
};

function RetentionSettings() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [cameraUuid, setCameraUuid] = useState('');
  const [search, setSearch] = useState('');
  const [days, setDays] = useState('');
  const [maxGb, setMaxGb] = useState('');
  const [overPolicy, setOverPolicy] = useState('delete_oldest');
  const [warnings, setWarnings] = useState<string[]>([]);

  const usageQuery = useQuery({ queryKey: ['storage-usage'], queryFn: getStorageUsage });
  const cameras = usageQuery.data ?? [];
  const q = search.trim().toLowerCase();
  const filtered = q ? cameras.filter((c) => c.name.toLowerCase().includes(q)) : cameras;
  const selected = cameraUuid || cameras[0]?.uuid || '';

  const policyQuery = useQuery({
    queryKey: ['policy', selected],
    queryFn: () => getPolicy(selected),
    enabled: !!selected,
  });

  useEffect(() => {
    const p = policyQuery.data;
    if (p) {
      setDays(p.retention_days != null ? String(p.retention_days) : '');
      setMaxGb(p.retention_max_bytes != null ? String(Math.round(p.retention_max_bytes / GB)) : '');
      setOverPolicy(p.over_capacity_policy);
    }
  }, [policyQuery.data]);

  const saveMut = useMutation({
    mutationFn: () =>
      updatePolicy(selected, {
        retention_days: days ? Number(days) : null,
        retention_max_bytes: maxGb ? Number(maxGb) * GB : null,
        over_capacity_policy: overPolicy as 'delete_oldest' | 'stop_recording' | 'warn_only',
      }),
    onSuccess: (p) => {
      setWarnings(p.warnings ?? []);
      void queryClient.invalidateQueries({ queryKey: ['storage-usage'] });
      toast.success(intl.formatMessage({ id: 'storage.policy_saved' }));
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'storage.retention' })}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <Input
          className="max-w-sm"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={intl.formatMessage({ id: 'common.search' })}
        />
        <div className="max-h-80 overflow-y-auto rounded border border-border">
          {filtered.map((c) => {
            const pct = c.retention_max_bytes ? Math.min(100, (c.used_bytes / c.retention_max_bytes) * 100) : null;
            return (
              <button
                key={c.uuid}
                type="button"
                onClick={() => setCameraUuid(c.uuid)}
                className={`flex w-full items-center gap-3 border-b border-border px-3 py-2 text-left text-sm last:border-b-0 hover:bg-secondary/60 ${
                  c.uuid === selected ? 'bg-secondary' : ''
                }`}
              >
                <span className="min-w-0 flex-1 truncate font-medium text-foreground">{c.name}</span>
                {c.has_override && (
                  <Badge variant="outline">{intl.formatMessage({ id: 'storage.policy_override' })}</Badge>
                )}
                {c.retention_days != null && (
                  <span className="text-xs text-muted-foreground">
                    {intl.formatMessage({ id: 'storage.retention_days' })} {c.retention_days}
                  </span>
                )}
                {pct != null && (
                  <span className="h-1.5 w-20 overflow-hidden rounded bg-muted">
                    <span
                      className={`block h-full ${pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-primary'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                )}
                <span className="w-24 text-right tabular-nums text-muted-foreground">{fmtUsage(c)}</span>
              </button>
            );
          })}
          {filtered.length === 0 && (
            <p className="p-4 text-center text-sm text-muted-foreground">
              {intl.formatMessage({ id: 'camera.empty' })}
            </p>
          )}
        </div>
        <p className="text-sm font-medium text-foreground">
          {cameras.find((c) => c.uuid === selected)?.name ?? ''}
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label>{intl.formatMessage({ id: 'storage.retention_days' })}</Label>
            <Input type="number" value={days} onChange={(e) => setDays(e.target.value)} placeholder="∞" />
          </div>
          <div className="space-y-2">
            <Label>{intl.formatMessage({ id: 'storage.retention_gb' })}</Label>
            <Input type="number" value={maxGb} onChange={(e) => setMaxGb(e.target.value)} placeholder="∞" />
          </div>
          <div className="space-y-2">
            <Label>{intl.formatMessage({ id: 'storage.over_capacity' })}</Label>
            <select
              className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
              value={overPolicy}
              onChange={(e) => setOverPolicy(e.target.value)}
            >
              <option value="delete_oldest">{intl.formatMessage({ id: 'storage.over.delete_oldest' })}</option>
              <option value="stop_recording">{intl.formatMessage({ id: 'storage.over.stop_recording' })}</option>
              <option value="warn_only">{intl.formatMessage({ id: 'storage.over.warn_only' })}</option>
            </select>
          </div>
        </div>
        {warnings.length > 0 && (
          <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
            {warnings.join(', ')}
          </div>
        )}
        <Button size="sm" disabled={!selected} onClick={() => saveMut.mutate()}>
          {intl.formatMessage({ id: 'common.save' })}
        </Button>
      </CardContent>
    </Card>
  );
}
