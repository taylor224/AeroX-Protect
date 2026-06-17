import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Aperture, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { CameraThumbnail } from '@/components/CameraThumbnail';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useFeatureFlag } from '@/lib/featureFlags';
import { deleteCamera, listCameras, updateCamera } from '@/pages/cameras/camera.api';
import { BatchAddDialog } from '@/pages/cameras/components/BatchAddDialog';
import { CameraAddWizard } from '@/pages/cameras/components/CameraAddWizard';
import { vendorLabel } from '@/pages/cameras/vendor';
import { CameraAiButton } from '@/pages/cameras/components/CameraAiButton';
import { CameraEditButton } from '@/pages/cameras/components/CameraEditButton';
import { CameraHealthBadge } from '@/pages/cameras/components/CameraHealthBadge';
import { DualRecordButton } from '@/pages/cameras/components/DualRecordButton';
import { EdgeImportButton } from '@/pages/cameras/components/EdgeImportButton';
import { MaskEditButton } from '@/pages/cameras/components/MaskEditButton';
import type { Camera } from '@/types/axp';

export function CamerasPage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canCreate = hasPermission('cameras', 'create');
  const canDelete = hasPermission('cameras', 'delete');
  const canUpdate = hasPermission('cameras', 'update');
  const batchEnabled = useFeatureFlag('batch_camera_add');
  const masksEnabled = useFeatureFlag('privacy_masks');
  const canMasks = hasPermission('masks', 'update');
  const canRecControl = hasPermission('recordings', 'control');

  const camerasQuery = useQuery({
    queryKey: ['cameras'],
    queryFn: () => listCameras(),
    refetchInterval: 15_000, // periodic health refresh (PLAN DoD #3)
  });

  const delMutation = useMutation({
    mutationFn: deleteCamera,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  });

  const fisheyeMut = useMutation({
    mutationFn: ({ uuid, on }: { uuid: string; on: boolean }) =>
      updateCamera(uuid, on ? { fisheye: true, fisheye_params: { cx: 0.5, cy: 0.5, radius: 0.5, lens_fov: Math.PI } } : { fisheye: false }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  });

  // fisheye dewarp is a per-camera display mode change → confirm before applying
  const [fisheyeConfirm, setFisheyeConfirm] = useState<Camera | null>(null);

  const cameras = camerasQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {intl.formatMessage({ id: 'menu.cameras' })}
        </h1>
        {canCreate && (
          <div className="flex items-center gap-2">
            {batchEnabled && (
              <BatchAddDialog onDone={() => queryClient.invalidateQueries({ queryKey: ['cameras'] })} />
            )}
            <CameraAddWizard onCreated={() => queryClient.invalidateQueries({ queryKey: ['cameras'] })} />
          </div>
        )}
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28" />
              <TableHead>{intl.formatMessage({ id: 'camera.name' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'camera.host' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'camera.vendor' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'camera.model' })}</TableHead>
              <TableHead>PTZ</TableHead>
              <TableHead>{intl.formatMessage({ id: 'camera.status' })}</TableHead>
              <TableHead className="text-right">{intl.formatMessage({ id: 'common.actions' })}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {camerasQuery.isLoading &&
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={8}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}

            {!camerasQuery.isLoading && cameras.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-sm text-muted-foreground">
                  {intl.formatMessage({ id: 'camera.empty' })}
                </TableCell>
              </TableRow>
            )}

            {cameras.map((cam) => (
              <TableRow key={cam.uuid}>
                <TableCell>
                  <CameraThumbnail cameraUuid={cam.uuid} status={cam.status} className="h-14 w-24 rounded" />
                </TableCell>
                <TableCell className="font-medium text-foreground">{cam.name}</TableCell>
                <TableCell className="text-muted-foreground">{cam.host}</TableCell>
                <TableCell>
                  <Badge variant="outline">{vendorLabel(cam.vendor)}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{cam.model ?? '—'}</TableCell>
                <TableCell>{cam.ptz_supported ? <Badge variant="muted">PTZ</Badge> : '—'}</TableCell>
                <TableCell>
                  <CameraHealthBadge status={cam.status} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-0.5 whitespace-nowrap">
                    {canUpdate && <CameraEditButton camera={cam} />}
                    {canUpdate && (
                      <Button
                        variant={cam.fisheye ? 'default' : 'ghost'}
                        size="icon"
                        onClick={() => setFisheyeConfirm(cam)}
                        title={intl.formatMessage({ id: 'camera.fisheye' })}
                        aria-label="fisheye"
                      >
                        <Aperture className="h-4 w-4" />
                      </Button>
                    )}
                    {canUpdate && <DualRecordButton camera={cam} />}
                    {canUpdate && <CameraAiButton camera={cam} />}
                    {canRecControl && <EdgeImportButton camera={cam} />}
                    {masksEnabled && canMasks && <MaskEditButton cameraUuid={cam.uuid} />}
                    {canDelete && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={async () => {
                          if (
                            await confirm({
                              title: intl.formatMessage({ id: 'confirm.delete.title' }),
                              description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: cam.name }),
                              confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                              destructive: true,
                            })
                          )
                            delMutation.mutate(cam.uuid);
                        }}
                        aria-label="delete"
                      >
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

      <ConfirmDialog
        open={!!fisheyeConfirm}
        onOpenChange={(v) => !v && setFisheyeConfirm(null)}
        title={intl.formatMessage({ id: 'camera.fisheye' })}
        description={intl.formatMessage(
          { id: fisheyeConfirm?.fisheye ? 'camera.fisheye_confirm_off' : 'camera.fisheye_confirm_on' },
          { name: fisheyeConfirm?.name ?? '' },
        )}
        confirmLabel={intl.formatMessage({ id: fisheyeConfirm?.fisheye ? 'common.turn_off' : 'common.turn_on' })}
        onConfirm={() => {
          if (fisheyeConfirm) fisheyeMut.mutate({ uuid: fisheyeConfirm.uuid, on: !fisheyeConfirm.fisheye });
        }}
      />
    </div>
  );
}
