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
import { listCameras } from '@/pages/cameras/camera.api';
import {
  discoverDisks,
  getPolicy,
  listDisks,
  registerDisk,
  updatePolicy,
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

      <RaidGuidanceCard />

      {canRetention && <RetentionSettings />}
    </div>
  );
}

function RaidGuidanceCard() {
  const intl = useIntl();
  return (
    <Card className="p-5">
      <details>
        <summary className="cursor-pointer text-sm font-medium text-foreground">
          {intl.formatMessage({ id: 'storage.raid.title' })}
        </summary>
        <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
          <p>{intl.formatMessage({ id: 'storage.raid.intro' })}</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>{intl.formatMessage({ id: 'storage.raid.mdadm' })}</li>
            <li>{intl.formatMessage({ id: 'storage.raid.zfs' })}</li>
            <li>{intl.formatMessage({ id: 'storage.raid.degraded' })}</li>
            <li>{intl.formatMessage({ id: 'storage.raid.smart' })}</li>
            <li>{intl.formatMessage({ id: 'storage.raid.encryption' })}</li>
          </ul>
        </div>
      </details>
    </Card>
  );
}

function RetentionSettings() {
  const intl = useIntl();
  const [cameraUuid, setCameraUuid] = useState('');
  const [days, setDays] = useState('');
  const [maxGb, setMaxGb] = useState('');
  const [overPolicy, setOverPolicy] = useState('delete_oldest');
  const [warnings, setWarnings] = useState<string[]>([]);

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];
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
      toast.success(intl.formatMessage({ id: 'storage.policy_saved' }));
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'storage.retention' })}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <div className="space-y-2">
            <Label>{intl.formatMessage({ id: 'camera.name' })}</Label>
            <select
              className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
              value={selected}
              onChange={(e) => setCameraUuid(e.target.value)}
            >
              {cameras.map((c) => (
                <option key={c.uuid} value={c.uuid}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
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
