import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Layers } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { updateCamera } from '@/pages/cameras/camera.api';
import type { Camera } from '@/types/axp';

/** Per-camera dual recording (R4): toggle it and choose WHICH stream is recorded as the
 *  secondary (main is always recorded). Blank = auto (prefer 'sub'). */
export function DualRecordButton({ camera }: { camera: Camera }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState(!!camera.dual_recording);
  const [stream, setStream] = useState(camera.dual_record_stream ?? '');

  const saveMut = useMutation({
    mutationFn: () => updateCamera(camera.uuid, { dual_recording: on, dual_record_stream: stream || null }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'camera.dual_saved' }));
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['cameras'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const roles = (camera.streams ?? []).map((s) => s.role);

  return (
    <>
      <Button
        variant={camera.dual_recording ? 'default' : 'ghost'}
        size="icon"
        onClick={() => setOpen(true)}
        title={intl.formatMessage({ id: 'camera.dual_recording' })}
        aria-label="dual recording"
      >
        <Layers className="h-4 w-4" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'camera.dual_recording' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{intl.formatMessage({ id: 'camera.dual_enable' })}</div>
                <div className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.dual_hint' })}</div>
              </div>
              <Switch checked={on} onCheckedChange={setOn} />
            </div>

            {on && (
              <div className="space-y-1.5">
                <div className="text-sm font-medium">{intl.formatMessage({ id: 'camera.dual_stream' })}</div>
                <select
                  className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={stream}
                  onChange={(e) => setStream(e.target.value)}
                >
                  <option value="">{intl.formatMessage({ id: 'camera.dual_auto' })}</option>
                  {roles.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
                <p className="text-[11px] text-muted-foreground">{intl.formatMessage({ id: 'camera.dual_stream_hint' })}</p>
              </div>
            )}

            <Button className="w-full" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
