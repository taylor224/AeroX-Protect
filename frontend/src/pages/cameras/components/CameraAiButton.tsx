import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { updateCamera } from '@/pages/cameras/camera.api';
import type { Camera } from '@/types/axp';

const FEATURES = ['audio', 'smoke', 'face', 'lpr'] as const;
type Feature = (typeof FEATURES)[number];

/** Per-camera AI feature toggles (audio classify / smoke / face / LPR). These used to be
 *  global feature flags; now each camera opts in. Detection itself needs the matching model
 *  on a detector node. */
export function CameraAiButton({ camera }: { camera: Camera }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [feat, setFeat] = useState<Record<Feature, boolean>>(() => ({
    audio: !!camera.ai_features?.audio,
    smoke: !!camera.ai_features?.smoke,
    face: !!camera.ai_features?.face,
    lpr: !!camera.ai_features?.lpr,
  }));

  const anyOn = FEATURES.some((f) => camera.ai_features?.[f]);

  const saveMut = useMutation({
    mutationFn: () => updateCamera(camera.uuid, { ai_features: feat }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'camera.ai_saved' }));
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['cameras'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  return (
    <>
      <Button
        variant={anyOn ? 'default' : 'ghost'}
        size="icon"
        onClick={() => setOpen(true)}
        title={intl.formatMessage({ id: 'camera.ai_features' })}
        aria-label="ai features"
      >
        <span className="text-xs font-semibold tracking-wide">AI</span>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'camera.ai_features' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.ai_hint' })}</p>
            {FEATURES.map((f) => (
              <div key={f} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div>
                  <div className="text-sm font-medium">{intl.formatMessage({ id: `camera.ai.${f}` })}</div>
                  <div className="text-xs text-muted-foreground">{intl.formatMessage({ id: `camera.ai.${f}.desc` })}</div>
                </div>
                <Switch checked={feat[f]} onCheckedChange={(v) => setFeat((p) => ({ ...p, [f]: v }))} />
              </div>
            ))}
            <Button className="w-full" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
