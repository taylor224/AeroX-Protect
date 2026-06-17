import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useFeatureFlag } from '@/lib/featureFlags';
import { createExport, downloadUrl, listExports } from '@/pages/playback/playback.api';

export function ExportPanel({
  cameraUuid,
  cameraId,
  from,
  to,
}: {
  cameraUuid: string;
  cameraId?: string;
  from: number;
  to: number;
}) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const watermarkEnabled = useFeatureFlag('export_watermark');
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'copy' | 'transcode'>('copy');
  const [watermark, setWatermark] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [password, setPassword] = useState('');

  const jobsQuery = useQuery({
    queryKey: ['exports'],
    queryFn: listExports,
    refetchInterval: 3000, // poll progress
  });

  const createMut = useMutation({
    mutationFn: () =>
      createExport({
        camera_uuid: cameraUuid,
        start_ts: from,
        end_ts: to,
        mode: watermark ? 'transcode' : mode,
        watermark: watermark || undefined,
        watermark_text: watermark && watermarkText ? watermarkText : undefined,
        password: password || undefined,
      }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'export.queued' }));
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['exports'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'export.failed' })),
  });

  // Only this camera's still-useful jobs — hide expired (download token gone) so the list
  // isn't cluttered with dead "copy · expired" entries.
  const jobs = (jobsQuery.data ?? []).filter(
    (j) => j.status !== 'expired' && (!cameraId || j.camera_id === cameraId),
  );

  return (
    <div className="space-y-2">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="outline" size="sm">
            {intl.formatMessage({ id: 'export.create' })}
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'export.create' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground">
              {new Date(from).toLocaleString()} → {new Date(to).toLocaleString()}
            </div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'export.mode' })}</Label>
              <select
                className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'copy' | 'transcode')}
              >
                <option value="copy">{intl.formatMessage({ id: 'export.copy' })}</option>
                <option value="transcode">{intl.formatMessage({ id: 'export.transcode' })}</option>
              </select>
            </div>

            {watermarkEnabled && (
              <div className="space-y-2 rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">
                      {intl.formatMessage({ id: 'export.watermark' })}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {intl.formatMessage({ id: 'export.watermark.desc' })}
                    </div>
                  </div>
                  <Switch checked={watermark} onCheckedChange={setWatermark} />
                </div>
                {watermark && (
                  <Input
                    value={watermarkText}
                    onChange={(e) => setWatermarkText(e.target.value)}
                    placeholder={intl.formatMessage({ id: 'export.watermark.ph' })}
                  />
                )}
              </div>
            )}

            {watermarkEnabled && (
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'export.password' })}</Label>
                <Input
                  type="text"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={intl.formatMessage({ id: 'export.password.ph' })}
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {intl.formatMessage({ id: 'common.cancel' })}
            </Button>
            <Button onClick={() => createMut.mutate()}>{intl.formatMessage({ id: 'common.create' })}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {jobs.length > 0 && (
        <div className="space-y-1 rounded-lg border border-border bg-background p-2">
          {jobs.slice(0, 5).map((job) => (
            <div key={job.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">
                {job.mode} · {job.status}
                {job.status === 'processing' ? ` ${job.progress}%` : ''}
              </span>
              {job.status === 'done' && job.download_token && (
                <a
                  href={downloadUrl(job.download_token)}
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  <Download className="h-3.5 w-3.5" />
                  {intl.formatMessage({ id: 'export.download' })}
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
