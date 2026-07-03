import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import {
  createEncodingNode,
  deleteEncodingNode,
  drainEncodingNode,
  listEncodeAssignments,
  listEncodingNodes,
  rebalanceEncoding,
} from '@/pages/ai/encode.api';

const STATUS_VARIANT: Record<string, 'default' | 'muted' | 'success' | 'danger'> = {
  online: 'success', degraded: 'default', offline: 'muted', draining: 'default', disabled: 'muted',
};

export function EncodingNodes() {
  const intl = useIntl();
  const confirm = useConfirm();
  const { locale } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [joinToken, setJoinToken] = useState<string | null>(null);

  const nodesQuery = useQuery({ queryKey: ['encoding-nodes'], queryFn: listEncodingNodes, refetchInterval: 5000 });
  const assignQuery = useQuery({ queryKey: ['encode-assignments'], queryFn: listEncodeAssignments, refetchInterval: 5000 });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['encoding-nodes'] });
    void queryClient.invalidateQueries({ queryKey: ['encode-assignments'] });
  };

  const createMut = useMutation({
    mutationFn: () => createEncodingNode(newName || 'encoder'),
    onSuccess: (res) => {
      setJoinToken(res.join_token);
      setNewName('');
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const drainMut = useMutation({ mutationFn: (id: string) => drainEncodingNode(id), onSuccess: invalidate });
  const delMut = useMutation({ mutationFn: (id: string) => deleteEncodingNode(id), onSuccess: invalidate });
  const rebalanceMut = useMutation({
    mutationFn: rebalanceEncoding,
    onSuccess: (r) => { toast.success(intl.formatMessage({ id: 'ai.rebalanced' }, { n: r.assigned })); invalidate(); },
  });

  const nodes = nodesQuery.data ?? [];
  const assignments = assignQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-foreground">{intl.formatMessage({ id: 'enc.nodes' })}</h2>
          <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'enc.subtitle' })}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => rebalanceMut.mutate()}>
            {intl.formatMessage({ id: 'ai.rebalance' })}
          </Button>
          <Button size="sm" onClick={() => { setJoinToken(null); setOpen(true); }}>
            {intl.formatMessage({ id: 'ai.add_node' })}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {nodes.map((n) => (
          <Card key={n.id} className="space-y-2 bg-card p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 font-medium">
                {n.name}
                <Badge variant={STATUS_VARIANT[n.status] ?? 'muted'}>{n.status}</Badge>
              </span>
              <div className="flex gap-1">
                <Button variant="ghost" size="sm" onClick={() => drainMut.mutate(n.id)}>
                  {intl.formatMessage({ id: 'ai.drain' })}
                </Button>
                <Button variant="ghost" size="icon" onClick={async () => {
                  if (await confirm({
                    title: intl.formatMessage({ id: 'confirm.delete.title' }),
                    description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: n.name }),
                    confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                    destructive: true,
                  }))
                    delMut.mutate(n.id);
                }}>
                  <Trash2 className="h-4 w-4 text-red-400" />
                </Button>
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>HW: {n.hwaccel || 'cpu'}</span>
              <span>{intl.formatMessage({ id: 'ai.load' })}: {n.assigned_count}/{n.max_sessions}</span>
              <span>♥ {formatDateTime(n.last_heartbeat_ts, locale)}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded bg-black/10">
              <div className="h-full bg-primary" style={{ width: `${n.max_sessions ? Math.min(100, (n.assigned_count / n.max_sessions) * 100) : 0}%` }} />
            </div>
          </Card>
        ))}
        {nodes.length === 0 && (
          <Card className="p-6 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'ai.no_nodes' })}</Card>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium text-foreground">{intl.formatMessage({ id: 'ai.assignments' })}</h2>
        <Card className="divide-y divide-border bg-card">
          {assignments.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'enc.no_assignments' })}</div>
          ) : (
            assignments.map((a) => (
              <div key={a.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>cam {a.camera_id} → {a.node_id}</span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="muted">{a.state}</Badge>
                  e{a.epoch} · ♥ {formatDateTime(a.last_report_ts, locale)}
                </span>
              </div>
            ))
          )}
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'ai.add_node' })}</DialogTitle>
          </DialogHeader>
          {joinToken ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'ai.join_token_hint' })}</p>
              <code className="block break-all rounded bg-black/40 p-2 text-xs text-emerald-300">{joinToken}</code>
              <code className="block break-all rounded bg-black/40 p-2 text-[11px] text-muted-foreground">
                docker run -e SERVER_API_URL=... -e JOIN_TOKEN={joinToken.slice(0, 12)}… axp-encoder
              </code>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="encoder-01" />
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            {!joinToken && (
              <Button disabled={createMut.isPending} onClick={() => createMut.mutate()}>
                {intl.formatMessage({ id: 'common.create' })}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
