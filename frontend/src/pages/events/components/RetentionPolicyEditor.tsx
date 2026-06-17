import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { getPolicy, updatePolicy } from '@/pages/storage/storage.api';
import type { StoragePolicy } from '@/types/p2';

const GB = 1024 ** 3;
const OVER = ['delete_oldest', 'stop_recording', 'warn_only'] as const;

/** Per-camera retention policy (PLAN P2). Keeps the tab focused on retention — recording is
 *  schedule-driven, so no record-mode toggle here. Blank fields = inherit the global policy. */
export function RetentionPolicyEditor({ cameraUuid, canEdit }: { cameraUuid: string; canEdit: boolean }) {
  const intl = useIntl();
  const qc = useQueryClient();
  const policyQuery = useQuery({ queryKey: ['storage-policy', cameraUuid], queryFn: () => getPolicy(cameraUuid) });

  const [days, setDays] = useState('');
  const [eventDays, setEventDays] = useState('');
  const [maxGb, setMaxGb] = useState('');
  const [over, setOver] = useState<StoragePolicy['over_capacity_policy']>('delete_oldest');
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    const p = policyQuery.data;
    if (!p) return;
    setDays(p.retention_days != null ? String(p.retention_days) : '');
    setEventDays(p.event_retention_days != null ? String(p.event_retention_days) : '');
    setMaxGb(p.retention_max_bytes ? String(Math.round(p.retention_max_bytes / GB)) : '');
    setOver(p.over_capacity_policy ?? 'delete_oldest');
  }, [policyQuery.data]);

  const num = (s: string) => (s.trim() === '' ? null : Math.max(0, Math.floor(Number(s))));
  const saveMut = useMutation({
    mutationFn: () =>
      updatePolicy(cameraUuid, {
        retention_days: num(days),
        event_retention_days: num(eventDays),
        retention_max_bytes: maxGb.trim() === '' ? null : Math.round(Number(maxGb) * GB),
        over_capacity_policy: over,
      }),
    onSuccess: (res) => {
      setWarnings(res.warnings ?? []);
      toast.success(intl.formatMessage({ id: 'retention.saved' }));
      qc.invalidateQueries({ queryKey: ['storage-policy', cameraUuid] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  return (
    <Card className="max-w-2xl space-y-5 bg-card p-5">
      <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'retention.subtitle' })}</p>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={intl.formatMessage({ id: 'retention.days' })} hint={intl.formatMessage({ id: 'retention.blank_global' })}>
          <Input type="number" min={0} value={days} disabled={!canEdit}
            onChange={(e) => setDays(e.target.value)} placeholder={intl.formatMessage({ id: 'retention.unlimited' })} />
        </Field>
        <Field label={intl.formatMessage({ id: 'retention.event_days' })} hint={intl.formatMessage({ id: 'retention.event_hint' })}>
          <Input type="number" min={0} value={eventDays} disabled={!canEdit}
            onChange={(e) => setEventDays(e.target.value)} placeholder={intl.formatMessage({ id: 'retention.unlimited' })} />
        </Field>
        <Field label={intl.formatMessage({ id: 'retention.max_gb' })} hint={intl.formatMessage({ id: 'retention.blank_global' })}>
          <Input type="number" min={0} value={maxGb} disabled={!canEdit}
            onChange={(e) => setMaxGb(e.target.value)} placeholder={intl.formatMessage({ id: 'retention.unlimited' })} />
        </Field>
        <Field label={intl.formatMessage({ id: 'retention.over' })} hint={intl.formatMessage({ id: 'retention.over_hint' })}>
          <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={over} disabled={!canEdit}
            onChange={(e) => setOver(e.target.value as StoragePolicy['over_capacity_policy'])}>
            {OVER.map((o) => (
              <option key={o} value={o}>{intl.formatMessage({ id: `retention.over.${o}` })}</option>
            ))}
          </select>
        </Field>
      </div>

      {warnings.length > 0 && (
        <div className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs text-amber-600">
          {warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              {w}
            </div>
          ))}
        </div>
      )}

      {canEdit && (
        <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
          {intl.formatMessage({ id: 'common.save' })}
        </Button>
      )}
    </Card>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
