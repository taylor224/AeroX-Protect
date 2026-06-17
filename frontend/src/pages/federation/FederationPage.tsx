import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Network, RefreshCw, Trash2 } from 'lucide-react';
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
  aggregatedCameras,
  createMember,
  deleteMember,
  listMembers,
  syncMember,
  type FederationMember,
} from '@/pages/federation/federation.api';

const STATUS_VARIANT: Record<string, 'success' | 'danger' | 'muted'> = {
  online: 'success', offline: 'danger', error: 'danger', unknown: 'muted',
};

export function FederationPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('federation');
  const canManage = hasPermission('federation', 'manage');

  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [token, setToken] = useState('');

  const membersQuery = useQuery({ queryKey: ['federation-members'], queryFn: listMembers, enabled, refetchInterval: enabled ? 10000 : false });
  const camerasQuery = useQuery({ queryKey: ['federation-cameras'], queryFn: aggregatedCameras, enabled });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['federation-members'] });
    queryClient.invalidateQueries({ queryKey: ['federation-cameras'] });
  };
  const addMut = useMutation({
    mutationFn: () => createMember({ name: name.trim(), base_url: baseUrl.trim(), token: token.trim() }),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'fed.added' })); setName(''); setBaseUrl(''); setToken(''); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'fed.add_failed' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteMember(id), onSuccess: invalidate });
  const syncMut = useMutation({
    mutationFn: (id: string) => syncMember(id),
    onSuccess: (m: FederationMember) => {
      toast[m.status === 'online' ? 'success' : 'error'](
        intl.formatMessage({ id: 'fed.synced' }, { n: m.camera_count }));
      invalidate();
    },
  });

  if (!enabled) {
    return (
      <Card className="p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'fed.disabled' })}
      </Card>
    );
  }

  const members = membersQuery.data ?? [];
  const cameras = camerasQuery.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
        <Network className="h-5 w-5" />
        {intl.formatMessage({ id: 'menu.federation' })}
      </h1>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* members */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'fed.members' })}</h2>
          {canManage && (
            <div className="space-y-2">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={intl.formatMessage({ id: 'fed.name_ph' })} />
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://site.example.com" />
              <Input value={token} onChange={(e) => setToken(e.target.value)} type="password" placeholder={intl.formatMessage({ id: 'fed.token_ph' })} />
              <Button size="sm" className="w-full" disabled={!name.trim() || !baseUrl.trim() || !token.trim() || addMut.isPending}
                onClick={() => addMut.mutate()}>
                {intl.formatMessage({ id: 'fed.add' })}
              </Button>
            </div>
          )}
          <div className="space-y-1">
            {members.map((m) => (
              <div key={m.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <Badge variant={STATUS_VARIANT[m.status] ?? 'muted'}>{m.status}</Badge>
                    <span className="font-medium">{m.name}</span>
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">{m.base_url} · {intl.formatMessage({ id: 'fed.cams' }, { n: m.camera_count })}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  {canManage && (
                    <Button variant="ghost" size="icon" aria-label="sync" disabled={syncMut.isPending}
                      onClick={() => syncMut.mutate(m.id)}>
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                  )}
                  {canManage && (
                    <Button variant="ghost" size="icon" aria-label="delete" onClick={async () => {
                      if (await confirm({
                        title: intl.formatMessage({ id: 'confirm.delete.title' }),
                        description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: m.name }),
                        confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                        destructive: true,
                      }))
                        delMut.mutate(m.id);
                    }}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </span>
              </div>
            ))}
            {members.length === 0 && (
              <p className="py-6 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'fed.no_members' })}</p>
            )}
          </div>
        </Card>

        {/* aggregated cameras */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'fed.all_cameras' }, { n: cameras.length })}</h2>
          <div className="max-h-[28rem] space-y-1 overflow-auto">
            {cameras.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
                <span className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${c.online ? 'bg-emerald-500' : 'bg-zinc-400'}`} />
                  <span className="font-medium">{c.name}</span>
                </span>
                <span className="text-xs text-muted-foreground">{c.member_name}</span>
              </div>
            ))}
            {cameras.length === 0 && (
              <p className="py-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'fed.no_cameras' })}</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
