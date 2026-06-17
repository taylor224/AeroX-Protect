import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Share2, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/axios';
import {
  createDashboard,
  deleteDashboard,
  getDashboard,
  listDashboards,
  removeAcl,
  setAcl,
} from '@/pages/dashboards/dashboard.api';
import { presetLayout } from '@/pages/live/layouts';
import type { ApiResponse, PageResult, UserRow } from '@/types/api';

export function DashboardsPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [shareUuid, setShareUuid] = useState<string | null>(null);

  const dashesQuery = useQuery({ queryKey: ['dashboards'], queryFn: listDashboards });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['dashboards'] });

  const createMut = useMutation({
    mutationFn: () => createDashboard(newName.trim(), presetLayout('4')),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'dashboard.saved' }));
      setCreateOpen(false);
      setNewName('');
      invalidate();
    },
  });
  const delMut = useMutation({ mutationFn: deleteDashboard, onSuccess: invalidate });

  const dashboards = dashesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {intl.formatMessage({ id: 'menu.dashboards' })}
        </h1>
        {hasPermission('dashboards', 'create') && (
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button>{intl.formatMessage({ id: 'dashboard.create' })}</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{intl.formatMessage({ id: 'dashboard.create' })}</DialogTitle>
              </DialogHeader>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'dashboard.name' })}</Label>
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus />
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setCreateOpen(false)}>
                  {intl.formatMessage({ id: 'common.cancel' })}
                </Button>
                <Button onClick={() => createMut.mutate()} disabled={!newName.trim()}>
                  {intl.formatMessage({ id: 'common.create' })}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{intl.formatMessage({ id: 'dashboard.name' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'dashboard.access' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'dashboard.shared' })}</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {dashboards.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-10 text-center text-sm text-muted-foreground">
                  {intl.formatMessage({ id: 'dashboard.empty' })}
                </TableCell>
              </TableRow>
            )}
            {dashboards.map((d) => (
              <TableRow key={d.uuid}>
                <TableCell className="font-medium text-foreground">{d.name}</TableCell>
                <TableCell>
                  <Badge variant="outline">{d.access ?? 'view'}</Badge>
                </TableCell>
                <TableCell>{d.is_shared ? <Badge variant="muted">shared</Badge> : '—'}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    {hasPermission('dashboards', 'share') && d.access === 'edit' && (
                      <Button variant="ghost" size="icon" onClick={() => setShareUuid(d.uuid)} aria-label="share">
                        <Share2 className="h-4 w-4" />
                      </Button>
                    )}
                    {hasPermission('dashboards', 'delete') && d.access === 'edit' && (
                      <Button variant="ghost" size="icon" onClick={async () => {
                        if (await confirm({
                          title: intl.formatMessage({ id: 'confirm.delete.title' }),
                          description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: d.name }),
                          confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                          destructive: true,
                        }))
                          delMut.mutate(d.uuid);
                      }} aria-label="delete">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {shareUuid && <ShareDialog dashboardUuid={shareUuid} onClose={() => setShareUuid(null)} />}
    </div>
  );
}

function ShareDialog({ dashboardUuid, onClose }: { dashboardUuid: string; onClose: () => void }) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState('');
  const [access, setAccess] = useState<'view' | 'edit'>('view');

  const detailQuery = useQuery({ queryKey: ['dashboard', dashboardUuid], queryFn: () => getDashboard(dashboardUuid) });
  const usersQuery = useQuery({
    queryKey: ['users-for-acl'],
    queryFn: async () => {
      const { data } = await api.get<ApiResponse<PageResult<UserRow>>>('/admin/users', {
        params: { items_per_page: 100 },
      });
      return data.data?.items ?? [];
    },
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardUuid] });
    void queryClient.invalidateQueries({ queryKey: ['dashboards'] });
  };

  const addMut = useMutation({
    mutationFn: () => setAcl(dashboardUuid, userId, access),
    onSuccess: () => {
      setUserId('');
      refresh();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'dashboard.share_failed' })),
  });
  const removeMut = useMutation({ mutationFn: (uid: string) => removeAcl(dashboardUuid, uid), onSuccess: refresh });

  const acl = detailQuery.data?.acl ?? [];

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{intl.formatMessage({ id: 'dashboard.share' })}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1.5">
              <Label>{intl.formatMessage({ id: 'dashboard.user' })}</Label>
              <select
                className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
              >
                <option value="">—</option>
                {(usersQuery.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.login_id})
                  </option>
                ))}
              </select>
            </div>
            <select
              className="h-10 rounded border border-input bg-background px-2 text-sm"
              value={access}
              onChange={(e) => setAccess(e.target.value as 'view' | 'edit')}
            >
              <option value="view">view</option>
              <option value="edit">edit</option>
            </select>
            <Button onClick={() => addMut.mutate()} disabled={!userId}>
              {intl.formatMessage({ id: 'common.create' })}
            </Button>
          </div>

          <div className="space-y-1">
            {acl.length === 0 && (
              <div className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'dashboard.no_acl' })}</div>
            )}
            {acl.map((a) => (
              <div key={a.user_id} className="flex items-center justify-between rounded bg-secondary px-2 py-1 text-sm">
                <span>
                  {a.user_id} · {a.access}
                </span>
                <Button variant="ghost" size="sm" onClick={async () => {
                  if (await confirm({
                    title: intl.formatMessage({ id: 'confirm.delete.title' }),
                    description: intl.formatMessage({ id: 'confirm.delete.desc' }),
                    confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                    destructive: true,
                  }))
                    removeMut.mutate(a.user_id);
                }}>
                  {intl.formatMessage({ id: 'common.delete' })}
                </Button>
              </div>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
