import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/axios';
import { useFeatureFlag } from '@/lib/featureFlags';
import {
  createSubscription,
  deleteSubscription,
  listSubscriptions,
  updateSubscription,
} from '@/pages/automation/automation.api';
import { EVENT_TYPES } from '@/types/p5';

const CHANNELS = ['inapp', 'push', 'email', 'webhook', 'sms'] as const;
const PRIORITIES = ['low', 'normal', 'high', 'critical'];

function urlB64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export function NotificationsTab() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const smsEnabled = useFeatureFlag('sms_notifications');
  const [draft, setDraft] = useState({ channel: 'inapp', event_types: ['motion'], min_priority: 'normal', batch_window_s: 0, sms_to: '' });

  const subsQuery = useQuery({ queryKey: ['notif-subs'], queryFn: listSubscriptions });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['notif-subs'] });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => updateSubscription(id, body),
    onSuccess: invalidate,
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const snoozedUntil = (s: { muted_until?: number | null }) =>
    s.muted_until && s.muted_until > Date.now() ? s.muted_until : null;

  const saveMut = useMutation({
    mutationFn: () => createSubscription(draft),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'auto.sub_saved' })); setOpen(false); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const pushMut = useMutation({
    mutationFn: async () => {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('unsupported');
      const { data } = await api.get<{ data: { public_key: string } }>('/push/vapid-public-key');
      const key = data.data?.public_key;
      if (!key) throw new Error('no_vapid');
      const reg = await navigator.serviceWorker.register('/sw.js');
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(key) as BufferSource });
      const json = sub.toJSON();
      await api.post('/push/subscriptions', { endpoint: json.endpoint, keys: json.keys, ua: navigator.userAgent });
    },
    onSuccess: () => toast.success(intl.formatMessage({ id: 'auto.push_enabled' })),
    onError: () => toast.error(intl.formatMessage({ id: 'auto.push_unsupported' })),
  });

  const subs = subsQuery.data ?? [];
  const toggle = (v: string) => setDraft((d) => ({ ...d, event_types: d.event_types.includes(v) ? d.event_types.filter((x) => x !== v) : [...d.event_types, v] }));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.notif_subtitle' })}</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => pushMut.mutate()}>{intl.formatMessage({ id: 'auto.enable_push' })}</Button>
          <Button size="sm" onClick={() => setOpen(true)}><Plus className="mr-1 h-4 w-4" />{intl.formatMessage({ id: 'auto.add_sub' })}</Button>
        </div>
      </div>
      <Card className="divide-y divide-border bg-card">
        {subs.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
            <span className="flex flex-wrap items-center gap-1.5">
              <Badge variant="default">{s.channel}</Badge>
              <span className="text-xs text-muted-foreground">{(s.event_types || ['all']).join(', ')} · ≥{s.min_priority}</span>
              {s.muted && <Badge variant="muted">{intl.formatMessage({ id: 'notif.mute' })}</Badge>}
              {snoozedUntil(s) && <Badge variant="muted">{intl.formatMessage({ id: 'notif.snooze' })}</Badge>}
            </span>
            <div className="flex shrink-0 items-center gap-1">
              <button
                onClick={() => updateMut.mutate({ id: s.id, body: { muted: !s.muted } })}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  s.muted ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary'
                }`}
              >
                {intl.formatMessage({ id: 'notif.mute' })}
              </button>
              <select
                value=""
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) return;
                  const until = v === 'off' ? Date.now() - 1000 : Date.now() + Number(v) * 1000;
                  updateMut.mutate({ id: s.id, body: { muted_until: until } });
                }}
                className="h-7 rounded border border-input bg-background px-1 text-xs text-muted-foreground"
              >
                <option value="">{intl.formatMessage({ id: 'notif.snooze' })}</option>
                <option value="3600">{intl.formatMessage({ id: 'notif.snooze.1h' })}</option>
                <option value="28800">{intl.formatMessage({ id: 'notif.snooze.8h' })}</option>
                {snoozedUntil(s) && <option value="off">{intl.formatMessage({ id: 'notif.snooze.off' })}</option>}
              </select>
              <Button variant="ghost" size="icon" onClick={async () => {
                if (await confirm({
                  title: intl.formatMessage({ id: 'confirm.delete.title' }),
                  description: intl.formatMessage({ id: 'confirm.delete.desc' }),
                  confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                  destructive: true,
                }))
                  deleteSubscription(s.id).then(invalidate);
              }}>
                <Trash2 className="h-4 w-4 text-red-400" />
              </Button>
            </div>
          </div>
        ))}
        {subs.length === 0 && <div className="p-4 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.no_subs' })}</div>}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{intl.formatMessage({ id: 'auto.add_sub' })}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'auto.channel' })}</Label>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={draft.channel}
                  onChange={(e) => setDraft({ ...draft, channel: e.target.value })}>
                  {CHANNELS.filter((c) => c !== 'sms' || smsEnabled).map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'auto.min_priority' })}</Label>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={draft.min_priority}
                  onChange={(e) => setDraft({ ...draft, min_priority: e.target.value })}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>
            {draft.channel === 'sms' && (
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'notif.sms_to' })}</Label>
                <Input
                  value={draft.sms_to}
                  onChange={(e) => setDraft({ ...draft, sms_to: e.target.value })}
                  placeholder="+15551234567"
                />
              </div>
            )}
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'auto.event_types' })}</Label>
              <div className="flex flex-wrap gap-1.5">
                {EVENT_TYPES.map((t) => (
                  <button key={t} onClick={() => toggle(t)}
                    className={`rounded-full border px-2.5 py-1 text-xs ${draft.event_types.includes(t) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'notif.batch' })}</Label>
              <Input type="number" min={0} value={draft.batch_window_s}
                onChange={(e) => setDraft({ ...draft, batch_window_s: Number(e.target.value) || 0 })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>{intl.formatMessage({ id: 'common.save' })}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
