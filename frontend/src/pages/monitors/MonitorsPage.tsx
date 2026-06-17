import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import {
  createMonitor,
  deleteMonitor,
  issuePairCode,
  listMonitors,
  revokeMonitor,
} from '@/pages/automation/automation.api';
import { listDashboards } from '@/pages/dashboards/dashboard.api';
import type { Monitor } from '@/types/p5';

const STATUS_VARIANT: Record<string, 'default' | 'muted' | 'success' | 'danger'> = {
  unpaired: 'muted', pending: 'default', paired: 'success', revoked: 'danger',
};

export function MonitorsPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const { locale } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [dashUuid, setDashUuid] = useState('');
  const [pairing, setPairing] = useState<{ name: string; code: string; left: number } | null>(null);

  const monitorsQuery = useQuery({ queryKey: ['monitors'], queryFn: listMonitors, refetchInterval: 5000 });
  const dashboardsQuery = useQuery({ queryKey: ['dashboards-list'], queryFn: listDashboards });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['monitors'] });

  const createMut = useMutation({
    mutationFn: () => createMonitor(name || 'monitor', dashUuid || dashboardsQuery.data?.[0]?.uuid || ''),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'mon.created' })); setOpen(false); setName(''); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const pairMut = useMutation({
    mutationFn: (m: Monitor) => issuePairCode(m.uuid).then((r) => ({ ...r, name: m.name })),
    onSuccess: (r) => { setPairing({ name: r.name, code: r.code, left: r.expires_in }); invalidate(); },
  });
  const revokeMut = useMutation({ mutationFn: (uuid: string) => revokeMonitor(uuid), onSuccess: invalidate });
  const delMut = useMutation({ mutationFn: (uuid: string) => deleteMonitor(uuid), onSuccess: invalidate });

  useEffect(() => {
    if (!pairing || pairing.left <= 0) return;
    const t = setInterval(() => setPairing((p) => (p ? { ...p, left: p.left - 1 } : p)), 1000);
    return () => clearInterval(t);
  }, [pairing]);

  const monitors = monitorsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.monitors' })}</h1>
        <Button size="sm" onClick={() => setOpen(true)}>{intl.formatMessage({ id: 'mon.add' })}</Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {monitors.map((m) => (
          <Card key={m.uuid} className="space-y-2 bg-card p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium">{m.name}</span>
              <Badge variant={STATUS_VARIANT[m.status] ?? 'muted'}>{m.status}</Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {intl.formatMessage({ id: 'mon.last_seen' })}: {formatDateTime(m.last_seen_at, locale)}
            </p>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" onClick={() => pairMut.mutate(m)}>{intl.formatMessage({ id: 'mon.pair' })}</Button>
              <Button variant="ghost" size="sm" onClick={async () => {
                if (await confirm({
                  title: intl.formatMessage({ id: 'confirm.revoke.title' }),
                  description: intl.formatMessage({ id: 'confirm.revoke.desc' }),
                  confirmLabel: intl.formatMessage({ id: 'common.revoke' }),
                  destructive: true,
                }))
                  revokeMut.mutate(m.uuid);
              }}>{intl.formatMessage({ id: 'mon.revoke' })}</Button>
              <Button variant="ghost" size="sm" onClick={async () => {
                if (await confirm({
                  title: intl.formatMessage({ id: 'confirm.delete.title' }),
                  description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: m.name }),
                  confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                  destructive: true,
                }))
                  delMut.mutate(m.uuid);
              }}>{intl.formatMessage({ id: 'common.delete' })}</Button>
            </div>
          </Card>
        ))}
        {monitors.length === 0 && (
          <Card className="p-6 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'mon.empty' })}</Card>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{intl.formatMessage({ id: 'mon.add' })}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>{intl.formatMessage({ id: 'mon.name' })}</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'mon.dashboard' })}</Label>
              <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={dashUuid} onChange={(e) => setDashUuid(e.target.value)}>
                {(dashboardsQuery.data ?? []).map((d) => <option key={d.uuid} value={d.uuid}>{d.name}</option>)}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            <Button disabled={createMut.isPending} onClick={() => createMut.mutate()}>{intl.formatMessage({ id: 'common.create' })}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!pairing} onOpenChange={(o) => !o && setPairing(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{intl.formatMessage({ id: 'mon.pair_title' }, { name: pairing?.name })}</DialogTitle></DialogHeader>
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="font-mono text-5xl tracking-[0.3em] text-foreground">{pairing?.code}</div>
            <p className="text-sm text-muted-foreground">
              {pairing && pairing.left > 0
                ? intl.formatMessage({ id: 'mon.code_hint' }, { s: pairing.left })
                : intl.formatMessage({ id: 'mon.code_expired' })}
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPairing(null)}>{intl.formatMessage({ id: 'common.confirm' })}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
