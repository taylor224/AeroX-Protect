import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HardDriveDownload } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { updateCamera } from '@/pages/cameras/camera.api';
import { listEdgeJobs, previewGaps, runEdgeImport, type EdgeGap } from '@/pages/cameras/edge.api';
import type { Camera } from '@/types/axp';

const STATUS_VARIANT: Record<string, 'default' | 'muted' | 'success' | 'danger'> = {
  queued: 'muted',
  running: 'muted',
  done: 'success',
  failed: 'danger',
};

const toLocalInput = (ms: number) => {
  const d = new Date(ms - new Date().getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
};
const fromLocalInput = (s: string) => new Date(s).getTime();
const fmtDur = (ms: number) => `${Math.round(ms / 1000)}s`;

/** Edge-recording (R6): enable SD gap-fill per camera, preview timeline gaps over a range,
 *  and queue an import of the camera's on-board clips into the NVR timeline. */
export function EdgeImportButton({ camera }: { camera: Camera }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const now = Date.now();
  const [start, setStart] = useState(() => toLocalInput(now - 3600_000));
  const [end, setEnd] = useState(() => toLocalInput(now));
  const [gaps, setGaps] = useState<EdgeGap[] | null>(null);

  const enabled = !!camera.edge_recording;
  const range = (): [number, number] => [fromLocalInput(start), fromLocalInput(end)];

  const jobsQuery = useQuery({
    queryKey: ['edge-jobs', camera.uuid],
    queryFn: () => listEdgeJobs(camera.uuid),
    enabled: open,
    refetchInterval: open ? 3000 : false,
  });

  const toggleMut = useMutation({
    mutationFn: (on: boolean) => updateCamera(camera.uuid, { edge_recording: on }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  });

  const autoMut = useMutation({
    mutationFn: (on: boolean) => updateCamera(camera.uuid, { edge_auto_import: on }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  });

  const gapsMut = useMutation({
    mutationFn: () => previewGaps(camera.uuid, ...range()),
    onSuccess: (g) => setGaps(g),
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const importMut = useMutation({
    mutationFn: () => runEdgeImport(camera.uuid, ...range()),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'edge.import_queued' }));
      jobsQuery.refetch();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const jobs = jobsQuery.data ?? [];

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setOpen(true)}
        title={intl.formatMessage({ id: 'edge.title' })}
        aria-label="edge recording"
      >
        <HardDriveDownload className="h-4 w-4" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'edge.title' })} · {camera.name}</DialogTitle>
          </DialogHeader>

          <div className="flex items-center justify-between rounded border border-border px-3 py-2">
            <div>
              <p className="text-sm font-medium">{intl.formatMessage({ id: 'edge.enable' })}</p>
              <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'edge.enable_hint' })}</p>
            </div>
            <Switch checked={enabled} onCheckedChange={(on) => toggleMut.mutate(on)} disabled={toggleMut.isPending} />
          </div>

          <div className="flex items-center justify-between rounded border border-border px-3 py-2">
            <div>
              <p className="text-sm font-medium">{intl.formatMessage({ id: 'edge.auto' })}</p>
              <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'edge.auto_hint' })}</p>
            </div>
            <Switch checked={!!camera.edge_auto_import} disabled={!enabled || autoMut.isPending}
              onCheckedChange={(on) => autoMut.mutate(on)} />
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-muted-foreground">
              {intl.formatMessage({ id: 'edge.from' })}
              <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1" />
            </label>
            <label className="text-xs text-muted-foreground">
              {intl.formatMessage({ id: 'edge.to' })}
              <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1" />
            </label>
            <Button variant="outline" size="sm" onClick={() => gapsMut.mutate()} disabled={gapsMut.isPending}>
              {intl.formatMessage({ id: 'edge.preview' })}
            </Button>
            <Button
              size="sm"
              onClick={() => importMut.mutate()}
              disabled={!enabled || importMut.isPending}
              title={!enabled ? intl.formatMessage({ id: 'edge.enable_first' }) : undefined}
            >
              {intl.formatMessage({ id: 'edge.import' })}
            </Button>
          </div>

          {gaps !== null && (
            <div className="rounded border border-border p-2 text-sm">
              {gaps.length === 0 ? (
                <p className="text-muted-foreground">{intl.formatMessage({ id: 'edge.no_gaps' })}</p>
              ) : (
                <p>{intl.formatMessage({ id: 'edge.gaps_found' }, { count: gaps.length, total: fmtDur(gaps.reduce((a, g) => a + g.duration_ms, 0)) })}</p>
              )}
            </div>
          )}

          <div className="max-h-44 space-y-1 overflow-auto">
            {jobs.map((j) => (
              <div key={j.id} className="flex items-center justify-between rounded border border-border px-2 py-1 text-sm">
                <span className="text-muted-foreground">
                  {j.created_at ? new Date(j.created_at).toLocaleString() : '—'}
                </span>
                <span className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    {j.clips_imported}/{j.clips_found}
                  </span>
                  <Badge variant={STATUS_VARIANT[j.status] ?? 'muted'}>{j.status}</Badge>
                </span>
              </div>
            ))}
            {jobs.length === 0 && (
              <p className="py-3 text-center text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'edge.no_jobs' })}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
