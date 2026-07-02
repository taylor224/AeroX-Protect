// Flows tab — list of visual automation flows; the editor lives at /rules/flows/:uuid.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GitBranch, Pencil, Plus, Trash2 } from 'lucide-react';
import { useIntl } from 'react-intl';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTime } from '@/lib/format';
import { deleteFlow, enableFlow, listFlows } from '@/pages/automation/flows/flow.api';
import type { Flow } from '@/types/flow';

export function FlowsTab() {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const navigate = useNavigate();
  const confirm = useConfirm();
  const queryClient = useQueryClient();

  const flowsQuery = useQuery({ queryKey: ['flows'], queryFn: listFlows });
  const flows = flowsQuery.data?.items ?? [];
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['flows'] });

  const enableMut = useMutation({
    mutationFn: ({ uuid, enabled }: { uuid: string; enabled: boolean }) => enableFlow(uuid, enabled),
    onSuccess: invalidate,
  });
  const deleteMut = useMutation({
    mutationFn: (uuid: string) => deleteFlow(uuid),
    onSuccess: () => { invalidate(); toast.success(fm('flow.deleted')); },
  });

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold text-foreground">{fm('flow.list.title')}</h2>
        <span className="text-xs text-muted-foreground">{fm('flow.list.subtitle')}</span>
        <div className="flex-1" />
        <Button size="sm" onClick={() => navigate('/rules/flows/new')}>
          <Plus className="mr-1 h-3.5 w-3.5" />{fm('flow.new')}
        </Button>
      </div>

      {flows.length === 0 && !flowsQuery.isLoading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">{fm('flow.list.empty')}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{fm('flow.col.name')}</TableHead>
              <TableHead>{fm('flow.col.nodes')}</TableHead>
              <TableHead>{fm('flow.col.lastRun')}</TableHead>
              <TableHead>{fm('flow.col.enabled')}</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {flows.map((f: Flow) => (
              <TableRow key={f.uuid} className="cursor-pointer"
                onClick={() => navigate(`/rules/flows/${f.uuid}`)}>
                <TableCell className="font-medium text-foreground">{f.name}</TableCell>
                <TableCell>
                  <Badge variant="muted">{f.graph?.nodes?.length ?? 0}</Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {f.last_run_ts ? formatDateTime(f.last_run_ts) : '—'}
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <Switch checked={f.enabled}
                    onCheckedChange={(v) => enableMut.mutate({ uuid: f.uuid, enabled: v })} />
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" onClick={() => navigate(`/rules/flows/${f.uuid}`)}>
                      <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                    <Button variant="ghost" size="icon"
                      onClick={async () => {
                        if (await confirm({
                          title: intl.formatMessage({ id: 'confirm.delete.title' }),
                          description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: f.name }),
                          confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                          destructive: true,
                        })) deleteMut.mutate(f.uuid);
                      }}>
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
