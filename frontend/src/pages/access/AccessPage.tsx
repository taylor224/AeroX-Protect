import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DoorOpen, Lock, LockOpen, Trash2 } from 'lucide-react';
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
import {
  createCredential,
  createDoor,
  deleteCredential,
  deleteDoor,
  listAccessEvents,
  listCredentials,
  listDoors,
  unlockDoor,
} from '@/pages/access/access.api';

export function AccessPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const qc = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('access_control');
  const canManage = hasPermission('access', 'manage');
  const canControl = hasPermission('access', 'control');

  const [doorName, setDoorName] = useState('');
  const [doorGroup, setDoorGroup] = useState('default');
  const [card, setCard] = useState('');
  const [holder, setHolder] = useState('');
  const [credGroup, setCredGroup] = useState('default');

  const doorsQuery = useQuery({ queryKey: ['doors'], queryFn: listDoors, enabled, refetchInterval: enabled ? 5000 : false });
  const credsQuery = useQuery({ queryKey: ['credentials'], queryFn: listCredentials, enabled });
  const eventsQuery = useQuery({ queryKey: ['access-events'], queryFn: listAccessEvents, enabled, refetchInterval: enabled ? 5000 : false });

  const inv = (k: string) => qc.invalidateQueries({ queryKey: [k] });
  const addDoor = useMutation({
    mutationFn: () => createDoor({ name: doorName.trim(), access_group: doorGroup.trim() || 'default' }),
    onSuccess: () => { setDoorName(''); inv('doors'); },
  });
  const delDoor = useMutation({ mutationFn: (id: string) => deleteDoor(id), onSuccess: () => inv('doors') });
  const unlockMut = useMutation({
    mutationFn: (id: string) => unlockDoor(id),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'access.unlocked' })); inv('doors'); inv('access-events'); },
  });
  const addCred = useMutation({
    mutationFn: () => createCredential({ card_number: card.trim(), holder_name: holder.trim(), access_group: credGroup.trim() || 'default' }),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'access.cred_added' })); setCard(''); setHolder(''); inv('credentials'); },
    onError: () => toast.error(intl.formatMessage({ id: 'access.cred_failed' })),
  });
  const delCred = useMutation({ mutationFn: (id: string) => deleteCredential(id), onSuccess: () => inv('credentials') });

  if (!enabled) {
    return <Card className="p-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'access.disabled' })}</Card>;
  }

  const doors = doorsQuery.data ?? [];
  const creds = credsQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
        <DoorOpen className="h-5 w-5" />
        {intl.formatMessage({ id: 'menu.access' })}
      </h1>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* doors */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'access.doors' })}</h2>
          {canManage && (
            <div className="flex gap-2">
              <Input value={doorName} onChange={(e) => setDoorName(e.target.value)} placeholder={intl.formatMessage({ id: 'access.door_name' })} />
              <Input value={doorGroup} onChange={(e) => setDoorGroup(e.target.value)} placeholder="group" className="w-28" />
              <Button size="sm" disabled={!doorName.trim() || addDoor.isPending} onClick={() => addDoor.mutate()}>
                {intl.formatMessage({ id: 'access.add' })}
              </Button>
            </div>
          )}
          <div className="space-y-1">
            {doors.map((d) => (
              <div key={d.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
                <span className="flex items-center gap-2">
                  {d.lock_state === 'unlocked'
                    ? <LockOpen className="h-4 w-4 text-emerald-600" />
                    : <Lock className="h-4 w-4 text-muted-foreground" />}
                  <span className="font-medium">{d.name}</span>
                  <Badge variant="muted">{d.access_group}</Badge>
                </span>
                <span className="flex items-center gap-1">
                  {canControl && (
                    <Button variant="outline" size="sm" disabled={unlockMut.isPending} onClick={() => unlockMut.mutate(d.id)}>
                      {intl.formatMessage({ id: 'access.unlock' })}
                    </Button>
                  )}
                  {canManage && (
                    <Button variant="ghost" size="icon" aria-label="delete" onClick={async () => {
                      if (await confirm({
                        title: intl.formatMessage({ id: 'confirm.delete.title' }),
                        description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: d.name }),
                        confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                        destructive: true,
                      }))
                        delDoor.mutate(d.id);
                    }}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </span>
              </div>
            ))}
            {doors.length === 0 && <p className="py-6 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'access.no_doors' })}</p>}
          </div>
        </Card>

        {/* credentials */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'access.credentials' })}</h2>
          {canManage && (
            <div className="grid grid-cols-2 gap-2">
              <Input value={card} onChange={(e) => setCard(e.target.value)} placeholder={intl.formatMessage({ id: 'access.card' })} className="font-mono" />
              <Input value={holder} onChange={(e) => setHolder(e.target.value)} placeholder={intl.formatMessage({ id: 'access.holder' })} />
              <Input value={credGroup} onChange={(e) => setCredGroup(e.target.value)} placeholder="group" />
              <Button size="sm" disabled={!card.trim() || !holder.trim() || addCred.isPending} onClick={() => addCred.mutate()}>
                {intl.formatMessage({ id: 'access.add' })}
              </Button>
            </div>
          )}
          <div className="max-h-60 space-y-1 overflow-auto">
            {creds.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
                <span className="flex items-center gap-2">
                  <span className="font-mono">{c.card_number}</span>
                  <span className="text-muted-foreground">{c.holder_name}</span>
                  <Badge variant="muted">{c.access_group}</Badge>
                  {!c.enabled && <Badge variant="danger">off</Badge>}
                </span>
                {canManage && (
                  <Button variant="ghost" size="icon" aria-label="delete" onClick={async () => {
                    if (await confirm({
                      title: intl.formatMessage({ id: 'confirm.delete.title' }),
                      description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: c.holder_name }),
                      confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                      destructive: true,
                    }))
                      delCred.mutate(c.id);
                  }}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {creds.length === 0 && <p className="py-6 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'access.no_creds' })}</p>}
          </div>
        </Card>
      </div>

      {/* access log */}
      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'access.log' })}</h2>
        <div className="max-h-72 space-y-1 overflow-auto">
          {events.map((e) => (
            <div key={e.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
              <span className="flex items-center gap-2">
                <Badge variant={e.decision === 'granted' ? 'success' : 'danger'}>{e.decision}</Badge>
                <span className="font-mono text-xs">{e.card_number ?? '—'}</span>
                <span className="text-muted-foreground">{e.holder_name ?? ''}</span>
                {e.reason && <span className="text-xs text-muted-foreground">({e.reason})</span>}
              </span>
              <span className="text-xs text-muted-foreground">{e.ts ? new Date(e.ts).toLocaleString() : '—'}</span>
            </div>
          ))}
          {events.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'access.no_events' })}</p>}
        </div>
      </Card>
    </div>
  );
}
