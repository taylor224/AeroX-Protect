import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { createTrigger, deleteTrigger, listTriggers, type TriggerInput } from '@/pages/ai/ai.api';
import { DETECTION_LABELS } from '@/types/p4';

interface Draft {
  scope: 'camera' | 'global';
  name: string;
  labels: string[];
  min_confidence: number;
  cooldown_s: number;
  notify: boolean;
  enabled: boolean;
}

const BLANK: Draft = { scope: 'camera', name: '', labels: ['person'], min_confidence: 50, cooldown_s: 30, notify: true, enabled: true };

export function ObjectTriggers({ cameraUuid, cameraName, canEdit }: { cameraUuid: string; cameraName: string; canEdit: boolean }) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(BLANK);

  const triggersQuery = useQuery({
    queryKey: ['triggers', cameraUuid],
    queryFn: () => listTriggers(cameraUuid),
    enabled: !!cameraUuid,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['triggers', cameraUuid] });

  const saveMut = useMutation({
    mutationFn: (d: Draft) => {
      const body: TriggerInput = {
        name: d.name || 'trigger', labels: d.labels, min_confidence: d.min_confidence,
        cooldown_s: d.cooldown_s, notify: d.notify, enabled: d.enabled,
      };
      if (d.scope === 'camera') body.camera_uuid = cameraUuid;
      return createTrigger(body);
    },
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'ai.trigger_saved' }));
      setOpen(false);
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (id: string) => deleteTrigger(id), onSuccess: invalidate });

  const triggers = triggersQuery.data ?? [];
  const toggleLabel = (l: string) =>
    setDraft((d) => ({ ...d, labels: d.labels.includes(l) ? d.labels.filter((x) => x !== l) : [...d.labels, l] }));

  return (
    <Card className="space-y-3 bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'ai.trigger_subtitle' })}</p>
        {canEdit && (
          <Button size="sm" onClick={() => { setDraft(BLANK); setOpen(true); }}>
            <Plus className="mr-1 h-4 w-4" />
            {intl.formatMessage({ id: 'ai.trigger_add' })}
          </Button>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{intl.formatMessage({ id: 'ai.trigger_name' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'ai.trigger_scope' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'ai.trigger_labels' })}</TableHead>
            <TableHead className="text-right">{intl.formatMessage({ id: 'ai.min_conf' })}</TableHead>
            <TableHead className="text-right">cd(s)</TableHead>
            <TableHead>{intl.formatMessage({ id: 'policy.enabled' })}</TableHead>
            {canEdit && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {triggers.map((t) => (
            <TableRow key={t.id}>
              <TableCell>{t.name}</TableCell>
              <TableCell>
                <Badge variant={t.camera_id ? 'default' : 'muted'}>
                  {t.camera_id ? cameraName : intl.formatMessage({ id: 'policy.global' })}
                </Badge>
              </TableCell>
              <TableCell className="text-xs">{(t.labels || []).join(', ')}</TableCell>
              <TableCell className="text-right tabular-nums">{t.min_confidence}</TableCell>
              <TableCell className="text-right tabular-nums">{t.cooldown_s}</TableCell>
              <TableCell>{t.enabled ? <Badge variant="success">on</Badge> : <Badge variant="muted">off</Badge>}</TableCell>
              {canEdit && (
                <TableCell>
                  <Button variant="ghost" size="icon" onClick={async () => {
                    if (await confirm({
                      title: intl.formatMessage({ id: 'confirm.delete.title' }),
                      description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: t.name }),
                      confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                      destructive: true,
                    }))
                      delMut.mutate(t.id);
                  }}>
                    <Trash2 className="h-4 w-4 text-red-400" />
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'ai.trigger_add' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'ai.trigger_name' })}</Label>
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'ai.trigger_labels' })}</Label>
              <div className="flex flex-wrap gap-1.5">
                {DETECTION_LABELS.map((l) => (
                  <button
                    key={l}
                    onClick={() => toggleLabel(l)}
                    className={`rounded-full border px-2.5 py-1 text-xs ${
                      draft.labels.includes(l) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'
                    }`}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'ai.trigger_scope' })}</Label>
                <select
                  className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={draft.scope}
                  onChange={(e) => setDraft({ ...draft, scope: e.target.value as Draft['scope'] })}
                >
                  <option value="camera">{cameraName}</option>
                  <option value="global">{intl.formatMessage({ id: 'policy.global' })}</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'ai.min_conf' })}</Label>
                <Input type="number" value={draft.min_confidence}
                  onChange={(e) => setDraft({ ...draft, min_confidence: Number(e.target.value) })} />
              </div>
              <div className="space-y-1.5">
                <Label>cooldown (s)</Label>
                <Input type="number" value={draft.cooldown_s}
                  onChange={(e) => setDraft({ ...draft, cooldown_s: Number(e.target.value) })} />
              </div>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <Switch checked={draft.notify} onCheckedChange={(v) => setDraft({ ...draft, notify: v })} />
                {intl.formatMessage({ id: 'policy.notify' })}
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            <Button disabled={saveMut.isPending || !draft.labels.length} onClick={() => saveMut.mutate(draft)}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
