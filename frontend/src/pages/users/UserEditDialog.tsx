import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { api } from '@/lib/axios';
import { listCameras } from '@/pages/cameras/camera.api';
import { listDashboards } from '@/pages/dashboards/dashboard.api';
import type { Role, UserRow } from '@/types/api';

// curated per-user feature grants (the role provides the base; these augment it)
const GRANTS: { key: string; resource: string; action: string }[] = [
  { key: 'live.read', resource: 'live', action: 'read' },
  { key: 'events.read', resource: 'events', action: 'read' },
  { key: 'recordings.read', resource: 'recordings', action: 'read' },
  { key: 'recordings.control', resource: 'recordings', action: 'control' },
  { key: 'cameras.read', resource: 'cameras', action: 'read' },
  { key: 'dashboards.read', resource: 'dashboards', action: 'read' },
  { key: 'dashboards.create', resource: 'dashboards', action: 'create' },
  { key: 'dashboards.update', resource: 'dashboards', action: 'update' },
  { key: 'ptz.control', resource: 'ptz', action: 'control' },
  { key: 'audio.talk', resource: 'audio', action: 'talk' },
];

type Perms = Record<string, unknown>;

async function updateUser(uuid: string, body: Record<string, unknown>) {
  await api.post(`/admin/users/${uuid}`, body);
}

const scopeKeys = (scope: Record<string, string[]> | undefined) =>
  Object.keys(scope ?? {}).filter((k) => k !== '*');
const scopeHasAction = (scope: Record<string, string[]> | undefined, action: string) =>
  Object.values(scope ?? {}).some((acts) => acts.includes(action));

export function UserEditDialog({
  user,
  roles,
  open,
  onOpenChange,
}: {
  user: UserRow;
  roles: Role[];
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const perms = (user.permissions ?? {}) as Perms;
  const camScope = perms.camera_scope as Record<string, string[]> | undefined;
  const dashScope = perms.dashboard_scope as Record<string, string[]> | undefined;

  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email ?? '');
  const [role, setRole] = useState(user.role ?? 'user');
  const [active, setActive] = useState(user.is_active);

  const [grants, setGrants] = useState<Set<string>>(
    () => new Set(GRANTS.filter((g) => (perms[g.resource] as string[] | undefined)?.includes(g.action)).map((g) => g.key)),
  );
  const [allCams, setAllCams] = useState(!!camScope?.['*']);
  const [selCams, setSelCams] = useState<Set<string>>(() => new Set(scopeKeys(camScope)));
  const [ptz, setPtz] = useState(scopeHasAction(camScope, 'ptz'));
  const [allDash, setAllDash] = useState(!!dashScope?.['*']);
  const [selDash, setSelDash] = useState<Set<string>>(() => new Set(scopeKeys(dashScope)));
  const [dashEdit, setDashEdit] = useState(scopeHasAction(dashScope, 'edit'));

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras(), enabled: open });
  const dashboardsQuery = useQuery({ queryKey: ['dashboards'], queryFn: listDashboards, enabled: open });
  const cameras = camerasQuery.data?.items ?? [];
  const dashboards = dashboardsQuery.data ?? [];

  const isAdminRole = role === 'admin';

  const toggle = (set: React.Dispatch<React.SetStateAction<Set<string>>>, key: string) =>
    set((prev) => {
      const n = new Set(prev);
      n.has(key) ? n.delete(key) : n.add(key);
      return n;
    });

  const builtPermissions = useMemo<Perms>(() => {
    const out: Perms = {};
    for (const g of GRANTS) {
      if (grants.has(g.key)) ((out[g.resource] as string[]) ??= []).push(g.action);
    }
    const camActs = ptz ? ['view', 'ptz'] : ['view'];
    if (allCams) out.camera_scope = { '*': camActs };
    else if (selCams.size) out.camera_scope = Object.fromEntries([...selCams].map((u) => [u, camActs]));
    const dashActs = dashEdit ? ['view', 'edit'] : ['view'];
    if (allDash) out.dashboard_scope = { '*': dashActs };
    else if (selDash.size) out.dashboard_scope = Object.fromEntries([...selDash].map((u) => [u, dashActs]));
    return out;
  }, [grants, allCams, selCams, ptz, allDash, selDash, dashEdit]);

  const saveMut = useMutation({
    mutationFn: () =>
      updateUser(user.uuid, {
        name: name.trim(),
        email: email.trim() || null,
        role,
        is_active: active,
        // admins already have full access via role; don't override their per-user perms
        permissions: isAdminRole ? user.permissions : builtPermissions,
      }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'users.updated' }));
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ['users'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const t = (id: string) => intl.formatMessage({ id });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-auto">
        <DialogHeader>
          <DialogTitle>{intl.formatMessage({ id: 'users.edit' }, { name: user.login_id })}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">{t('users.name')}</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">{t('users.email')}</span>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">{t('users.role')}</span>
              <select className="h-10 w-full rounded border border-input bg-background px-3 text-sm"
                value={role} onChange={(e) => setRole(e.target.value)}>
                {roles.map((r) => <option key={r.name} value={r.name}>{r.display_name}</option>)}
              </select>
            </label>
            <label className="flex items-end justify-between gap-2 pb-1">
              <span className="text-xs text-muted-foreground">{t('users.active')}</span>
              <Switch checked={active} onCheckedChange={setActive} />
            </label>
          </div>

          {isAdminRole ? (
            <p className="text-xs text-muted-foreground">{t('users.admin_full')}</p>
          ) : (
            <>
              {/* feature grants */}
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t('users.perm.features')}</h3>
                <div className="grid grid-cols-2 gap-1.5">
                  {GRANTS.map((g) => (
                    <label key={g.key} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={grants.has(g.key)} onChange={() => toggle(setGrants, g.key)} />
                      {t(`perm.${g.key}`)}
                    </label>
                  ))}
                </div>
              </section>

              {/* camera scope */}
              <section className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{t('users.perm.cameras')}</h3>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    {t('users.perm.all')}
                    <Switch checked={allCams} onCheckedChange={setAllCams} />
                  </label>
                </div>
                {!allCams && (
                  <div className="max-h-32 space-y-1 overflow-auto rounded border border-border p-2">
                    {cameras.map((c) => (
                      <label key={c.uuid} className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={selCams.has(c.uuid)} onChange={() => toggle(setSelCams, c.uuid)} />
                        {c.name}
                      </label>
                    ))}
                    {cameras.length === 0 && <p className="text-xs text-muted-foreground">{t('camera.empty')}</p>}
                  </div>
                )}
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input type="checkbox" checked={ptz} onChange={(e) => setPtz(e.target.checked)} />
                  {t('users.perm.include_ptz')}
                </label>
              </section>

              {/* dashboard scope */}
              <section className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{t('users.perm.dashboards')}</h3>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    {t('users.perm.all')}
                    <Switch checked={allDash} onCheckedChange={setAllDash} />
                  </label>
                </div>
                {!allDash && (
                  <div className="max-h-28 space-y-1 overflow-auto rounded border border-border p-2">
                    {dashboards.map((d) => (
                      <label key={d.uuid} className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={selDash.has(d.uuid)} onChange={() => toggle(setSelDash, d.uuid)} />
                        {d.name}
                      </label>
                    ))}
                    {dashboards.length === 0 && <p className="text-xs text-muted-foreground">—</p>}
                  </div>
                )}
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input type="checkbox" checked={dashEdit} onChange={(e) => setDashEdit(e.target.checked)} />
                  {t('users.perm.include_edit')}
                </label>
              </section>
            </>
          )}

          <Button className="w-full" disabled={saveMut.isPending || !name.trim()} onClick={() => saveMut.mutate()}>
            {t('common.save')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
