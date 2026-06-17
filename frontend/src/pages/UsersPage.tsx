import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MoreHorizontal } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';
import { z } from 'zod';

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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useTranslation } from '@/i18n/TranslationProvider';
import { api } from '@/lib/axios';
import { formatDateTime } from '@/lib/format';
import { UserEditDialog } from '@/pages/users/UserEditDialog';
import type { ApiResponse, PageResult, Role, UserRow } from '@/types/api';

async function fetchUsers(page: number): Promise<PageResult<UserRow>> {
  const { data } = await api.get<ApiResponse<PageResult<UserRow>>>('/admin/users', {
    params: { page, items_per_page: 20, sort: 'created_at', order: 'desc' },
  });
  return data.data as PageResult<UserRow>;
}

async function fetchRoles(): Promise<Role[]> {
  const { data } = await api.get<ApiResponse<Role[]>>('/admin/roles');
  return data.data ?? [];
}

function statusBadge(user: UserRow, intl: ReturnType<typeof useIntl>) {
  if (user.locked_until && user.locked_until > Date.now()) {
    return <Badge variant="danger">{intl.formatMessage({ id: 'users.locked' })}</Badge>;
  }
  if (user.is_active) {
    return <Badge variant="success">{intl.formatMessage({ id: 'users.active' })}</Badge>;
  }
  return <Badge variant="muted">{intl.formatMessage({ id: 'users.inactive' })}</Badge>;
}

const createSchema = z.object({
  login_id: z.string().min(1),
  name: z.string().min(1),
  password: z.string().min(8),
  email: z.string().email().optional().or(z.literal('')),
  role: z.string().min(1),
});
type CreateValues = z.infer<typeof createSchema>;

export function UsersPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const { locale } = useTranslation();
  const { hasPermission } = useAuthContext();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [editUser, setEditUser] = useState<UserRow | null>(null);

  const canCreate = hasPermission('users', 'create');
  const canUpdate = hasPermission('users', 'update');
  const canDelete = hasPermission('users', 'delete');

  const usersQuery = useQuery({ queryKey: ['users', page], queryFn: () => fetchUsers(page) });
  const rolesQuery = useQuery({ queryKey: ['roles'], queryFn: fetchRoles });
  const roleLabel = (name: string | null) =>
    (rolesQuery.data ?? []).find((r) => r.name === name)?.display_name ?? name ?? '—';

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['users'] });

  const createMutation = useMutation({
    mutationFn: (values: CreateValues) =>
      api.post('/admin/users', { ...values, email: values.email || null }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'users.created' }));
      setCreateOpen(false);
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (uuid: string) => api.delete(`/admin/users/${uuid}`),
    onSuccess: invalidate,
  });

  const unlockMutation = useMutation({
    mutationFn: (uuid: string) => api.post(`/admin/users/${uuid}/unlock`),
    onSuccess: invalidate,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { login_id: '', name: '', password: '', email: '', role: 'user' },
  });

  const onCreate = (values: CreateValues) => createMutation.mutateAsync(values);
  const result = usersQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {intl.formatMessage({ id: 'users.title' })}
        </h1>
        {canCreate && (
          <Dialog
            open={createOpen}
            onOpenChange={(open) => {
              setCreateOpen(open);
              if (!open) reset();
            }}
          >
            <DialogTrigger asChild>
              <Button>{intl.formatMessage({ id: 'users.create' })}</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{intl.formatMessage({ id: 'users.create' })}</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleSubmit(onCreate)} className="space-y-3" noValidate>
                <Field label={intl.formatMessage({ id: 'users.login_id' })} error={!!errors.login_id}>
                  <Input autoFocus {...register('login_id')} />
                </Field>
                <Field label={intl.formatMessage({ id: 'users.name' })} error={!!errors.name}>
                  <Input {...register('name')} />
                </Field>
                <Field label={intl.formatMessage({ id: 'users.password' })} error={!!errors.password}>
                  <Input type="password" autoComplete="new-password" {...register('password')} />
                </Field>
                <Field label={intl.formatMessage({ id: 'users.email' })} error={!!errors.email}>
                  <Input type="email" {...register('email')} />
                </Field>
                <Field label={intl.formatMessage({ id: 'users.role' })} error={!!errors.role}>
                  <select
                    className="flex h-10 w-full rounded border border-input bg-background px-3 text-sm"
                    {...register('role')}
                  >
                    {(rolesQuery.data ?? [{ name: 'user', display_name: '사용자' } as Role]).map((r) => (
                      <option key={r.name} value={r.name}>
                        {r.display_name}
                      </option>
                    ))}
                  </select>
                </Field>
                <DialogFooter>
                  <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                    {intl.formatMessage({ id: 'common.cancel' })}
                  </Button>
                  <Button type="submit" disabled={isSubmitting}>
                    {intl.formatMessage({ id: 'common.create' })}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{intl.formatMessage({ id: 'users.login_id' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'users.name' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'users.role' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'users.status' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'users.last_login' })}</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {usersQuery.isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}

            {result?.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  {intl.formatMessage({ id: 'users.empty' })}
                </TableCell>
              </TableRow>
            )}

            {result?.items.map((user) => {
              const isLocked = !!user.locked_until && user.locked_until > Date.now();
              return (
                <TableRow key={user.uuid}>
                  <TableCell className="font-medium text-foreground">{user.login_id}</TableCell>
                  <TableCell>{user.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{roleLabel(user.role)}</Badge>
                  </TableCell>
                  <TableCell>{statusBadge(user, intl)}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(user.last_login_at, locale)}
                  </TableCell>
                  <TableCell>
                    {(canUpdate || canDelete) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label="actions">
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {canUpdate && (
                            <DropdownMenuItem onClick={() => setEditUser(user)}>
                              {intl.formatMessage({ id: 'common.edit' })}
                            </DropdownMenuItem>
                          )}
                          {canUpdate && isLocked && (
                            <DropdownMenuItem onClick={() => unlockMutation.mutate(user.uuid)}>
                              {intl.formatMessage({ id: 'users.unlock' })}
                            </DropdownMenuItem>
                          )}
                          {canDelete && (
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={async () => {
                                if (
                                  await confirm({
                                    title: intl.formatMessage({ id: 'confirm.delete.title' }),
                                    description: intl.formatMessage(
                                      { id: 'confirm.delete.named' },
                                      { name: user.name },
                                    ),
                                    confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                                    destructive: true,
                                  })
                                )
                                  deleteMutation.mutate(user.uuid);
                              }}
                            >
                              {intl.formatMessage({ id: 'common.delete' })}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>

      {result && result.pagination.total_pages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ‹
          </Button>
          <span className="text-sm text-white/70">
            {result.pagination.page} / {result.pagination.total_pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= result.pagination.total_pages}
            onClick={() => setPage((p) => p + 1)}
          >
            ›
          </Button>
        </div>
      )}

      {editUser && (
        <UserEditDialog
          user={editUser}
          roles={rolesQuery.data ?? []}
          open={!!editUser}
          onOpenChange={(o) => !o && setEditUser(null)}
        />
      )}
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className={error ? 'text-destructive' : undefined}>{label}</Label>
      {children}
    </div>
  );
}
