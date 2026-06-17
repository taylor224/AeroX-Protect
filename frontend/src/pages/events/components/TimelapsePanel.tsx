import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, X } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { cancelTimelapse, createTimelapse, listTimelapse, timelapseDownloadUrl } from '@/pages/events/events.api';
import type { TimelapseStatus } from '@/types/p3';

const SPEEDS = [30, 60, 120, 300, 600];

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const STATUS_VARIANT: Record<TimelapseStatus, 'default' | 'muted' | 'success' | 'danger'> = {
  queued: 'muted',
  running: 'default',
  done: 'success',
  failed: 'danger',
  canceled: 'muted',
};

export function TimelapsePanel({ cameraUuid, canCreate }: { cameraUuid: string; canCreate: boolean }) {
  const intl = useIntl();
  const { locale } = useTranslation();
  const queryClient = useQueryClient();

  const now = Date.now();
  const [start, setStart] = useState(() => toLocalInput(new Date(now - 24 * 3600_000)));
  const [end, setEnd] = useState(() => toLocalInput(new Date(now)));
  const [speed, setSpeed] = useState(60);

  const jobsQuery = useQuery({
    queryKey: ['timelapse', cameraUuid],
    queryFn: () => listTimelapse(cameraUuid),
    enabled: !!cameraUuid,
    refetchInterval: 3000, // poll progress
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['timelapse', cameraUuid] });
  const createMut = useMutation({
    mutationFn: () =>
      createTimelapse({
        camera_uuid: cameraUuid,
        range_start: new Date(start).getTime(),
        range_end: new Date(end).getTime(),
        speed_factor: speed,
      }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'timelapse.queued' }));
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelTimelapse(id),
    onSuccess: invalidate,
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const jobs = jobsQuery.data ?? [];
  const future = new Date(end).getTime() > Date.now();

  return (
    <Card className="space-y-4 bg-card p-4">
      {canCreate && (
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'timelapse.range_start' })}</Label>
            <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className="w-56" />
          </div>
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'timelapse.range_end' })}</Label>
            <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} className="w-56" />
          </div>
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'timelapse.speed' })}</Label>
            <select
              className="h-10 w-28 rounded border border-input bg-background px-2 text-sm"
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            >
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  ×{s}
                </option>
              ))}
            </select>
          </div>
          <Button disabled={createMut.isPending} onClick={() => createMut.mutate()}>
            {intl.formatMessage({ id: 'timelapse.create' })}
          </Button>
          {future && (
            <p className="w-full text-xs text-amber-500">{intl.formatMessage({ id: 'timelapse.future_hint' })}</p>
          )}
        </div>
      )}

      <div className="space-y-1.5">
        {jobs.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {intl.formatMessage({ id: 'timelapse.empty' })}
          </p>
        ) : (
          jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
                <span className="text-muted-foreground">
                  {formatDateTime(job.range_start_ts, locale)} → {formatDateTime(job.range_end_ts, locale)}
                </span>
                <span className="text-xs text-muted-foreground">×{job.speed_factor}</span>
              </div>
              <div className="flex items-center gap-3">
                {job.status === 'running' && <span className="text-xs tabular-nums">{job.progress}%</span>}
                {job.status === 'done' && (
                  <a
                    href={timelapseDownloadUrl(job.id)}
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    <Download className="h-4 w-4" />
                    {intl.formatMessage({ id: 'timelapse.download' })}
                  </a>
                )}
                {job.status === 'failed' && job.error && (
                  <span className="max-w-[240px] truncate text-xs text-red-400" title={job.error}>
                    {job.error}
                  </span>
                )}
                {(job.status === 'queued' || job.status === 'running') && canCreate && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-muted-foreground hover:text-red-400"
                    disabled={cancelMut.isPending}
                    onClick={() => cancelMut.mutate(job.id)}
                  >
                    <X className="mr-1 h-3.5 w-3.5" />
                    {intl.formatMessage({ id: 'timelapse.cancel' })}
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
