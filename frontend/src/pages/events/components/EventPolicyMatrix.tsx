import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  createPolicy,
  deletePolicy,
  listPolicies,
  updatePolicy,
  type PolicyInput,
} from '@/pages/events/events.api';
import { EVENT_TYPES, POLICY_ACTIONS, type EventPolicy } from '@/types/p3';

interface DraftState {
  id?: string;
  scope: 'global' | 'camera';
  event_type: string;
  action: EventPolicy['action'];
  pre_buffer_s: number;
  post_buffer_s: number;
  cooldown_s: number;
  min_score: string; // text input → optional int
  notify: boolean;
  enabled: boolean;
}

const BLANK: DraftState = {
  scope: 'camera',
  event_type: 'motion',
  action: 'record',
  pre_buffer_s: 5,
  post_buffer_s: 10,
  cooldown_s: 10,
  min_score: '',
  notify: true,
  enabled: true,
};

function fromPolicy(p: EventPolicy): DraftState {
  return {
    id: p.id,
    scope: p.camera_id ? 'camera' : 'global',
    event_type: p.event_type,
    action: p.action,
    pre_buffer_s: p.pre_buffer_s,
    post_buffer_s: p.post_buffer_s,
    cooldown_s: p.cooldown_s,
    min_score: p.min_score == null ? '' : String(p.min_score),
    notify: p.notify,
    enabled: p.enabled,
  };
}

export function EventPolicyMatrix({
  cameraUuid,
  cameraName,
  canEdit,
}: {
  cameraUuid: string;
  cameraName: string;
  canEdit: boolean;
}) {
  const intl = useIntl();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftState>(BLANK);

  const policiesQuery = useQuery({
    queryKey: ['policies', cameraUuid],
    queryFn: () => listPolicies(cameraUuid),
    enabled: !!cameraUuid,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['policies', cameraUuid] });

  const saveMut = useMutation({
    mutationFn: (d: DraftState) => {
      const body: PolicyInput = {
        event_type: d.event_type,
        action: d.action,
        pre_buffer_s: d.pre_buffer_s,
        post_buffer_s: d.post_buffer_s,
        cooldown_s: d.cooldown_s,
        min_score: d.min_score.trim() === '' ? null : Number(d.min_score),
        notify: d.notify,
        enabled: d.enabled,
      };
      if (d.id) return updatePolicy(d.id, body);
      if (d.scope === 'camera') body.camera_uuid = cameraUuid;
      return createPolicy(body);
    },
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'policy.saved' }));
      setOpen(false);
      invalidate();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePolicy(id),
    onSuccess: invalidate,
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const policies = policiesQuery.data ?? [];

  const openCreate = () => {
    setDraft(BLANK);
    setOpen(true);
  };
  const openEdit = (p: EventPolicy) => {
    setDraft(fromPolicy(p));
    setOpen(true);
  };

  return (
    <Card className="space-y-3 bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'policy.subtitle' })}</p>
        {canEdit && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-1 h-4 w-4" />
            {intl.formatMessage({ id: 'policy.add' })}
          </Button>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{intl.formatMessage({ id: 'policy.scope' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'policy.event_type' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'policy.action' })}</TableHead>
            <TableHead className="text-right">
              <span className="inline-flex items-center justify-end">
                {intl.formatMessage({ id: 'policy.timing' })}
                <InfoTip text={intl.formatMessage({ id: 'policy.timing.help' })} />
              </span>
            </TableHead>
            <TableHead className="text-right">{intl.formatMessage({ id: 'policy.min_score' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'policy.enabled' })}</TableHead>
            {canEdit && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {policies.map((p) => (
            <TableRow key={p.id}>
              <TableCell>
                <Badge variant={p.camera_id ? 'default' : 'muted'}>
                  {p.camera_id
                    ? cameraName
                    : intl.formatMessage({ id: 'policy.global' })}
                </Badge>
              </TableCell>
              <TableCell>{intl.formatMessage({ id: `event.type.${p.event_type}`, defaultMessage: p.event_type })}</TableCell>
              <TableCell>
                <Badge variant={p.action === 'record' ? 'success' : p.action === 'discard' ? 'muted' : 'default'}>
                  {intl.formatMessage({ id: `policy.action.${p.action}`, defaultMessage: p.action })}
                </Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums text-xs text-muted-foreground">
                {p.pre_buffer_s}/{p.post_buffer_s}/{p.cooldown_s}
              </TableCell>
              <TableCell className="text-right tabular-nums">{p.min_score ?? '—'}</TableCell>
              <TableCell>
                {p.enabled ? (
                  <Badge variant="success">on</Badge>
                ) : (
                  <Badge variant="muted">off</Badge>
                )}
              </TableCell>
              {canEdit && (
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" onClick={() => openEdit(p)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={async () => {
                      if (await confirm({
                        title: intl.formatMessage({ id: 'confirm.delete.title' }),
                        description: intl.formatMessage({ id: 'confirm.delete.desc' }),
                        confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                        destructive: true,
                      }))
                        deleteMut.mutate(p.id);
                    }}>
                      <Trash2 className="h-4 w-4 text-red-400" />
                    </Button>
                  </div>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {intl.formatMessage({ id: draft.id ? 'policy.edit' : 'policy.add' })}
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            {!draft.id && (
              <Field label={intl.formatMessage({ id: 'policy.scope' })}>
                <select
                  className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={draft.scope}
                  onChange={(e) => setDraft({ ...draft, scope: e.target.value as DraftState['scope'] })}
                >
                  <option value="camera">{cameraName}</option>
                  <option value="global">{intl.formatMessage({ id: 'policy.global' })}</option>
                </select>
              </Field>
            )}
            <Field label={intl.formatMessage({ id: 'policy.event_type' })}>
              <select
                className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                value={draft.event_type}
                onChange={(e) => setDraft({ ...draft, event_type: e.target.value })}
              >
                <option value="*">{intl.formatMessage({ id: 'policy.all_types' })}</option>
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {intl.formatMessage({ id: `event.type.${t}`, defaultMessage: t })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={intl.formatMessage({ id: 'policy.action' })}>
              <select
                className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                value={draft.action}
                onChange={(e) => setDraft({ ...draft, action: e.target.value as EventPolicy['action'] })}
              >
                {POLICY_ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {intl.formatMessage({ id: `policy.action.${a}`, defaultMessage: a })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={intl.formatMessage({ id: 'policy.min_score' })}>
              <Input
                inputMode="numeric"
                value={draft.min_score}
                onChange={(e) => setDraft({ ...draft, min_score: e.target.value.replace(/[^0-9]/g, '') })}
                placeholder="—"
              />
            </Field>
            <Field label={intl.formatMessage({ id: 'policy.pre' })}>
              <Input
                type="number"
                value={draft.pre_buffer_s}
                onChange={(e) => setDraft({ ...draft, pre_buffer_s: Number(e.target.value) })}
              />
            </Field>
            <Field label={intl.formatMessage({ id: 'policy.post' })}>
              <Input
                type="number"
                value={draft.post_buffer_s}
                onChange={(e) => setDraft({ ...draft, post_buffer_s: Number(e.target.value) })}
              />
            </Field>
            <Field
              label={
                <span className="inline-flex items-center">
                  {intl.formatMessage({ id: 'policy.cooldown' })}
                  <InfoTip text={intl.formatMessage({ id: 'policy.cooldown.help' })} />
                </span>
              }
            >
              <Input
                type="number"
                value={draft.cooldown_s}
                onChange={(e) => setDraft({ ...draft, cooldown_s: Number(e.target.value) })}
              />
            </Field>
            <div className="col-span-2 flex items-center gap-6 pt-1">
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={draft.notify} onCheckedChange={(v) => setDraft({ ...draft, notify: v })} />
                {intl.formatMessage({ id: 'policy.notify' })}
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={draft.enabled} onCheckedChange={(v) => setDraft({ ...draft, enabled: v })} />
                {intl.formatMessage({ id: 'policy.enabled' })}
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {intl.formatMessage({ id: 'common.cancel' })}
            </Button>
            <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate(draft)}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

/** Small (?) hint — shows its text on hover and toggles on click. */
function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative ml-1 inline-flex">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border text-[10px] leading-none text-muted-foreground hover:bg-secondary"
        aria-label="help"
      >
        ?
      </button>
      {open && (
        <span className="absolute bottom-full left-1/2 z-50 mb-1 w-60 -translate-x-1/2 rounded-md border border-border bg-popover px-2.5 py-1.5 text-left text-xs font-normal text-popover-foreground shadow-md">
          {text}
        </span>
      )}
    </span>
  );
}
