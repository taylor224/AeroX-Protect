import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HardDriveUpload, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useFeatureFlag } from '@/lib/featureFlags';
import {
  createJob,
  createTarget,
  deleteTarget,
  listJobs,
  listTargets,
} from '@/pages/archive/archive.api';

const TYPES = ['s3', 'smb', 'local'] as const;
const GB = 1024 ** 3;
const fmtBytes = (b: number) => (b >= GB ? `${(b / GB).toFixed(1)} GB` : `${(b / 1024 / 1024).toFixed(0)} MB`);

export function ArchivePage() {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('archiving');
  const canRun = hasPermission('archive', 'run');

  const targetsQuery = useQuery({ queryKey: ['archive-targets'], queryFn: listTargets, enabled });
  const jobsQuery = useQuery({ queryKey: ['archive-jobs'], queryFn: listJobs, enabled, refetchInterval: 4000 });

  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({ name: '', type: 'local' });
  const [runTarget, setRunTarget] = useState('');
  const [runRef, setRunRef] = useState('');

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['archive-targets'] });
    void queryClient.invalidateQueries({ queryKey: ['archive-jobs'] });
  };

  const createTargetMut = useMutation({
    mutationFn: () => {
      const t = draft.type;
      const config: Record<string, unknown> =
        t === 's3'
          ? { bucket: draft.bucket, prefix: draft.prefix, region: draft.region, endpoint: draft.endpoint }
          : t === 'smb'
            ? { host: draft.host, share: draft.share, path: draft.path }
            : { path: draft.path };
      const secrets: Record<string, string> =
        t === 's3'
          ? { access_key: draft.access_key || '', secret_key: draft.secret_key || '' }
          : t === 'smb'
            ? { username: draft.username || '', password: draft.password || '' }
            : {};
      return createTarget({ name: draft.name, type: t as 's3' | 'smb' | 'local', config, secrets });
    },
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'archive.target_saved' }));
      setOpen(false);
      setDraft({ name: '', type: 'local' });
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const runMut = useMutation({
    mutationFn: () => createJob(runTarget, runRef.trim()),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'archive.job_queued' }));
      setRunRef('');
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  if (!enabled) {
    return (
      <Card className="mx-auto mt-10 max-w-lg p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'archive.disabled' })}
      </Card>
    );
  }

  const targets = targetsQuery.data ?? [];
  const jobs = jobsQuery.data ?? [];
  const targetName = (id: string) => targets.find((t) => t.id === id)?.name ?? id;
  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.archive' })}</h1>
        {canRun && (
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />
            {intl.formatMessage({ id: 'archive.add_target' })}
          </Button>
        )}
      </div>

      {/* targets */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {targets.map((t) => (
          <Card key={t.id} className="flex items-start justify-between gap-3 p-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium text-foreground">{t.name}</span>
                <Badge variant="muted">{t.type}</Badge>
                {!t.enabled && <Badge variant="outline">off</Badge>}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {t.type === 's3' ? String((t.config as { bucket?: string })?.bucket ?? '') : String((t.config as { path?: string })?.path ?? '')}
              </div>
            </div>
            {canRun && (
              <Button variant="ghost" size="icon" onClick={async () => {
                if (await confirm({
                  title: intl.formatMessage({ id: 'confirm.delete.title' }),
                  description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: t.name }),
                  confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                  destructive: true,
                }))
                  deleteTarget(t.id).then(invalidate);
              }} aria-label="delete">
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            )}
          </Card>
        ))}
        {targets.length === 0 && (
          <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-3">
            {intl.formatMessage({ id: 'archive.no_targets' })}
          </Card>
        )}
      </div>

      {/* run a job */}
      {canRun && targets.length > 0 && (
        <Card className="flex flex-wrap items-end gap-3 p-4">
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'archive.target' })}</Label>
            <select className="h-10 rounded border border-input bg-background px-2 text-sm" value={runTarget || targets[0].id}
              onChange={(e) => setRunTarget(e.target.value)}>
              {targets.filter((t) => t.enabled).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'archive.recording_id' })}</Label>
            <Input value={runRef} onChange={(e) => setRunRef(e.target.value)} placeholder="recording id" className="w-48" />
          </div>
          <Button size="sm" disabled={!runRef.trim() || runMut.isPending}
            onClick={() => runMut.mutate()}>
            <HardDriveUpload className="mr-1 h-4 w-4" />
            {intl.formatMessage({ id: 'archive.run' })}
          </Button>
        </Card>
      )}

      {/* jobs */}
      <Card className="divide-y divide-border">
        {jobs.map((j) => (
          <div key={j.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
            <span className="flex items-center gap-2">
              <span className="text-foreground">{targetName(j.target_id)}</span>
              <span className="text-xs text-muted-foreground">rec {j.source_ref}</span>
            </span>
            <span className="flex items-center gap-3 text-xs text-muted-foreground">
              {j.status === 'running' && <span>{j.progress}%</span>}
              {j.bytes_done > 0 && <span>{fmtBytes(j.bytes_done)}</span>}
              <Badge variant={j.status === 'done' ? 'default' : j.status === 'failed' ? 'danger' : 'muted'}>
                {j.status}
              </Badge>
            </span>
          </div>
        ))}
        {jobs.length === 0 && (
          <div className="p-6 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'archive.no_jobs' })}</div>
        )}
      </Card>

      {/* add target dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'archive.add_target' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'archive.name' })}</Label>
                <Input value={draft.name} onChange={(e) => set('name', e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'archive.type' })}</Label>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm" value={draft.type}
                  onChange={(e) => set('type', e.target.value)}>
                  {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>

            {draft.type === 's3' && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <Input placeholder="bucket" value={draft.bucket || ''} onChange={(e) => set('bucket', e.target.value)} />
                  <Input placeholder="prefix/" value={draft.prefix || ''} onChange={(e) => set('prefix', e.target.value)} />
                  <Input placeholder="region" value={draft.region || ''} onChange={(e) => set('region', e.target.value)} />
                  <Input placeholder="endpoint (optional)" value={draft.endpoint || ''} onChange={(e) => set('endpoint', e.target.value)} />
                  <Input placeholder="access key" value={draft.access_key || ''} onChange={(e) => set('access_key', e.target.value)} />
                  <Input type="password" placeholder="secret key" value={draft.secret_key || ''} onChange={(e) => set('secret_key', e.target.value)} />
                </div>
              </>
            )}
            {draft.type === 'smb' && (
              <div className="grid grid-cols-2 gap-3">
                <Input placeholder="host" value={draft.host || ''} onChange={(e) => set('host', e.target.value)} />
                <Input placeholder="share" value={draft.share || ''} onChange={(e) => set('share', e.target.value)} />
                <Input placeholder="path" value={draft.path || ''} onChange={(e) => set('path', e.target.value)} />
                <Input placeholder="username" value={draft.username || ''} onChange={(e) => set('username', e.target.value)} />
                <Input type="password" placeholder="password" value={draft.password || ''} onChange={(e) => set('password', e.target.value)} />
              </div>
            )}
            {draft.type === 'local' && (
              <Input placeholder="/mnt/archive" value={draft.path || ''} onChange={(e) => set('path', e.target.value)} />
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            <Button size="sm" disabled={!draft.name || createTargetMut.isPending} onClick={() => createTargetMut.mutate()}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
