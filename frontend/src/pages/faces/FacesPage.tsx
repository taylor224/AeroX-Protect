import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ScanFace, Trash2, UserPlus } from 'lucide-react';
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
import { listCameras } from '@/pages/cameras/camera.api';
import {
  createIdentity,
  deleteIdentity,
  enrollFromObservation,
  listAllFaces,
  listIdentities,
} from '@/pages/faces/face.api';

export function FacesPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('face');
  const canManage = hasPermission('face', 'manage');

  const [name, setName] = useState('');
  const [enrollTarget, setEnrollTarget] = useState('');

  // camera_id → name, so each (cross-camera) observation can show where it came from
  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];
  const cameraName = (id: string) => cameras.find((c) => c.id === id)?.name ?? '—';

  const idsQuery = useQuery({ queryKey: ['face-identities'], queryFn: listIdentities, enabled });
  const facesQuery = useQuery({
    queryKey: ['face-obs', 'all'],
    queryFn: () => listAllFaces(),
    enabled,
    refetchInterval: enabled ? 5000 : false,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['face-identities'] });
  const addMut = useMutation({
    mutationFn: () => createIdentity({ name: name.trim(), consent: true }),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'face.added' })); setName(''); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteIdentity(id), onSuccess: invalidate });
  const enrollMut = useMutation({
    mutationFn: ({ identityId, obsId }: { identityId: string; obsId: string }) => enrollFromObservation(identityId, obsId),
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'face.enrolled' })); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'face.enroll_failed' })),
  });

  if (!enabled) {
    return (
      <Card className="p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'face.disabled' })}
      </Card>
    );
  }

  const identities = idsQuery.data ?? [];
  const faces = facesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
        <ScanFace className="h-5 w-5" />
        {intl.formatMessage({ id: 'menu.faces' })}
      </h1>
      <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'face.privacy_note' })}</p>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* observations */}
        <Card className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'face.recent' })}</h2>
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'face.all_cameras' })}</span>
          </div>
          {canManage && identities.length > 0 && (
            <select className="h-9 w-full rounded border border-input bg-background px-2 text-sm"
              value={enrollTarget} onChange={(e) => setEnrollTarget(e.target.value)}>
              <option value="">{intl.formatMessage({ id: 'face.enroll_pick' })}</option>
              {identities.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
          )}
          <div className="max-h-[26rem] space-y-1 overflow-auto">
            {faces.map((f) => (
              <div key={f.id} className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
                <span className="flex items-center gap-2">
                  {f.identity_name
                    ? <Badge variant="success">{f.identity_name}</Badge>
                    : <Badge variant="muted">{intl.formatMessage({ id: 'face.unknown' })}</Badge>}
                  {f.score != null && <span className="text-xs text-muted-foreground tabular-nums">{f.score}</span>}
                </span>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <span className="text-xs">{cameraName(f.camera_id)}</span>
                  <span className="text-xs tabular-nums">{f.ts ? new Date(f.ts).toLocaleTimeString() : '—'}</span>
                  {canManage && enrollTarget && !f.identity_name && (
                    <Button variant="ghost" size="icon" aria-label="enroll"
                      onClick={() => enrollMut.mutate({ identityId: enrollTarget, obsId: f.id })}>
                      <UserPlus className="h-4 w-4" />
                    </Button>
                  )}
                </span>
              </div>
            ))}
            {faces.length === 0 && (
              <p className="py-10 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'face.no_obs' })}</p>
            )}
          </div>
        </Card>

        {/* identities */}
        <Card className="space-y-3 p-4">
          <h2 className="text-sm font-semibold">{intl.formatMessage({ id: 'face.identities' })}</h2>
          {canManage && (
            <div className="space-y-2">
              <Input value={name} onChange={(e) => setName(e.target.value)}
                placeholder={intl.formatMessage({ id: 'face.name_ph' })} />
              <Button size="sm" className="w-full" disabled={!name.trim() || addMut.isPending}
                onClick={() => addMut.mutate()}>
                {intl.formatMessage({ id: 'face.add' })}
              </Button>
            </div>
          )}
          <div className="max-h-80 space-y-1 overflow-auto">
            {identities.map((i) => (
              <div key={i.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
                <span className="flex items-center gap-2">
                  <span className="font-medium">{i.name}</span>
                  <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'face.refs' }, { n: i.embedding_count })}</span>
                </span>
                {canManage && (
                  <Button variant="ghost" size="icon" onClick={async () => {
                    if (await confirm({
                      title: intl.formatMessage({ id: 'confirm.delete.title' }),
                      description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: i.name }),
                      confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                      destructive: true,
                    }))
                      delMut.mutate(i.id);
                  }} aria-label="delete">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </div>
            ))}
            {identities.length === 0 && (
              <p className="py-6 text-center text-xs text-muted-foreground">{intl.formatMessage({ id: 'face.no_identities' })}</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
