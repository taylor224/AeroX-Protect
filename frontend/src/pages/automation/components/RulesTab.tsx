import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Plus, Trash2, Zap } from 'lucide-react';
import { type ReactNode, useState } from 'react';
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
import { env } from '@/config/env';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { listCameras } from '@/pages/cameras/camera.api';
import {
  createRule,
  deleteRule,
  enableRule,
  listExecutions,
  listRules,
  listTargets,
  triggerRule,
} from '@/pages/automation/automation.api';
import { listIdentities } from '@/pages/faces/face.api';
import {
  ACTION_TYPES,
  OBJECT_CLASSES,
  SYSTEM_EVENTS,
  type ActionType,
  type RuleAction,
  type TriggerType,
} from '@/types/p5';

const TRIGGER_TYPES: TriggerType[] = ['event', 'object', 'system_event', 'schedule', 'incoming_webhook', 'manual'];
// event types offered for the "event" trigger (human labels via the event.type.* namespace)
const EVENT_TRIGGER_TYPES = ['motion', 'object', 'intrusion', 'tamper', 'loitering', 'line_crossing',
  'doorbell_call', 'audio_class', 'face', 'lpr'] as const;

type ScheduleRepeat = 'daily' | 'weekdays' | 'weekends' | 'custom';
interface CondEvent { type: string; camera: 'same' | 'any' }

interface Draft {
  name: string;
  trigger_type: TriggerType;
  event_types: string[];
  classes: string[];
  system_events: string[];
  min_confidence: number;
  camera_ids: string[];
  device_ids: string[];
  identity_ids: string[];
  use_min_score: boolean;
  min_score: number;
  sched_repeat: ScheduleRepeat;
  sched_days: number[];
  sched_hour: number;
  sched_minute: number;
  cond_mode: 'all' | 'any';     // AND (all) / OR (any) across the extra event conditions
  cond_window_s: number;
  cond_events: CondEvent[];
  actions: RuleAction[];
}

const BLANK: Draft = {
  name: '', trigger_type: 'event', event_types: ['motion'], classes: ['person'],
  system_events: ['camera_offline'], min_confidence: 60, camera_ids: [], device_ids: [], identity_ids: [],
  use_min_score: false, min_score: 50,
  sched_repeat: 'weekdays', sched_days: [1, 2, 3, 4, 5], sched_hour: 9, sched_minute: 0,
  cond_mode: 'all', cond_window_s: 30, cond_events: [],
  actions: [],
};

function hookUrl(token: string): string {
  return `${window.location.origin}${env.apiUrl}/automation/incoming/${token}`;
}

// friendly schedule → 5-field cron (dow 0=Sun..6=Sat)
function toCron(d: Draft): string {
  const dow = d.sched_repeat === 'daily' ? '*'
    : d.sched_repeat === 'weekdays' ? '1-5'
    : d.sched_repeat === 'weekends' ? '0,6'
    : (d.sched_days.length ? [...d.sched_days].sort((a, b) => a - b).join(',') : '*');
  return `${d.sched_minute} ${d.sched_hour} * * ${dow}`;
}

export function RulesTab() {
  const intl = useIntl();
  const confirm = useConfirm();
  const { locale } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [draft, setDraft] = useState<Draft>(BLANK);
  const openWizard = () => { setDraft(BLANK); setStep(1); setOpen(true); };
  const patch = (p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p }));

  const rulesQuery = useQuery({ queryKey: ['rules'], queryFn: listRules });
  const targetsQuery = useQuery({ queryKey: ['action-targets'], queryFn: listTargets });
  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const identitiesQuery = useQuery({
    queryKey: ['face-identities'], queryFn: listIdentities,
    enabled: open && draft.trigger_type === 'event' && draft.event_types.includes('face'),
  });
  const execQuery = useQuery({ queryKey: ['rule-exec'], queryFn: () => listExecutions(), refetchInterval: 5000 });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['rules'] });
    void queryClient.invalidateQueries({ queryKey: ['rule-exec'] });
  };

  const cameras = camerasQuery.data?.items ?? [];
  const targets = targetsQuery.data ?? [];
  const identities = identitiesQuery.data ?? [];

  const saveMut = useMutation({
    mutationFn: (d: Draft) => {
      const trigger: Record<string, unknown> =
        d.trigger_type === 'event' ? { event_types: d.event_types, ...(d.identity_ids.length ? { identity_ids: d.identity_ids.map(Number) } : {}) }
        : d.trigger_type === 'object' ? { classes: d.classes, min_confidence: d.min_confidence }
        : d.trigger_type === 'system_event' ? { event_types: d.system_events }
        : d.trigger_type === 'schedule' ? { cron: toCron(d) } : {};
      const condition: Record<string, unknown> = {};
      if (d.camera_ids.length) condition.camera_ids = d.camera_ids.map(Number);
      if (d.device_ids.length) condition.device_ids = d.device_ids.map(Number);
      if (d.use_min_score) condition.min_score = d.min_score;
      if (d.cond_events.length) {
        condition.correlate = { window_s: d.cond_window_s, mode: d.cond_mode, events: d.cond_events };
      }
      return createRule({
        name: d.name || 'rule', trigger_type: d.trigger_type, trigger, condition,
        actions: d.actions, cooldown_s: 30,
      });
    },
    onSuccess: () => { toast.success(intl.formatMessage({ id: 'auto.rule_saved' })); setOpen(false); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const delMut = useMutation({ mutationFn: (uuid: string) => deleteRule(uuid), onSuccess: invalidate });
  const enableMut = useMutation({ mutationFn: (v: { uuid: string; on: boolean }) => enableRule(v.uuid, v.on), onSuccess: invalidate });
  const fireMut = useMutation({
    mutationFn: (uuid: string) => triggerRule(uuid),
    onSuccess: (r) => { toast.success(`${intl.formatMessage({ id: 'auto.fired' })}: ${r.status}`); invalidate(); },
  });

  const rules = rulesQuery.data?.items ?? [];
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const setActions = (actions: RuleAction[]) => patch({ actions });

  const evLabel = (t: string) => intl.formatMessage({ id: `event.type.${t}`, defaultMessage: t });
  const sysLabel = (e: string) => intl.formatMessage({ id: `sysevent.${e}`, defaultMessage: e });
  const objLabel = (c: string) => intl.formatMessage({ id: `objclass.${c}`, defaultMessage: c });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.rules_subtitle' })}</p>
        <Button size="sm" onClick={openWizard}>
          <Plus className="mr-1 h-4 w-4" />{intl.formatMessage({ id: 'auto.add_rule' })}
        </Button>
      </div>

      <Card className="bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{intl.formatMessage({ id: 'auto.rule_name' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'auto.trigger' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'auto.actions' })}</TableHead>
              <TableHead>{intl.formatMessage({ id: 'policy.enabled' })}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.map((r) => (
              <TableRow key={r.uuid}>
                <TableCell>
                  {r.name}
                  {r.trigger_type === 'incoming_webhook' && r.incoming_token && (
                    <button
                      onClick={() => { void navigator.clipboard?.writeText(hookUrl(r.incoming_token!)); toast.success(intl.formatMessage({ id: 'auto.hook_copied' })); }}
                      className="mt-1 flex max-w-xs items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-primary"
                      title={hookUrl(r.incoming_token)}>
                      <Copy className="h-3 w-3 shrink-0" />
                      <span className="truncate">{hookUrl(r.incoming_token)}</span>
                    </button>
                  )}
                </TableCell>
                <TableCell><Badge variant="muted">{intl.formatMessage({ id: `auto.trig.${r.trigger_type}`, defaultMessage: r.trigger_type })}</Badge></TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {(r.actions || []).map((a) => intl.formatMessage({ id: `auto.act.${a.type}`, defaultMessage: a.type })).join(', ') || '—'}
                </TableCell>
                <TableCell>
                  <Switch checked={r.enabled} onCheckedChange={(on) => enableMut.mutate({ uuid: r.uuid, on })} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" onClick={() => fireMut.mutate(r.uuid)} title={intl.formatMessage({ id: 'auto.fire' })}>
                      <Zap className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={async () => {
                      if (await confirm({
                        title: intl.formatMessage({ id: 'confirm.delete.title' }),
                        description: intl.formatMessage({ id: 'confirm.delete.named' }, { name: r.name }),
                        confirmLabel: intl.formatMessage({ id: 'common.delete' }),
                        destructive: true,
                      }))
                        delMut.mutate(r.uuid);
                    }}>
                      <Trash2 className="h-4 w-4 text-red-400" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">{intl.formatMessage({ id: 'auto.executions' })}</h3>
        <Card className="max-h-72 divide-y divide-border overflow-auto bg-card">
          {(execQuery.data?.items ?? []).map((e) => (
            <div key={e.id} className="flex items-center justify-between px-3 py-1.5 text-xs">
              <span className="text-muted-foreground">{formatDateTime(e.created_at, locale)} · {e.trigger_type}</span>
              <Badge variant={e.status === 'success' ? 'success' : e.status === 'skipped' ? 'muted' : 'danger'}>
                {e.status}{e.skip_reason ? `:${e.skip_reason}` : ''}
              </Badge>
            </div>
          ))}
          {(execQuery.data?.items ?? []).length === 0 && (
            <div className="p-4 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.no_exec' })}</div>
          )}
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-auto">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'auto.add_rule' })}</DialogTitle>
          </DialogHeader>

          <div className="flex items-center gap-2 text-xs font-medium">
            <span className={step === 1 ? 'text-primary' : 'text-muted-foreground'}>1. {intl.formatMessage({ id: 'auto.step_trigger' })}</span>
            <span className="text-muted-foreground">→</span>
            <span className={step === 2 ? 'text-primary' : 'text-muted-foreground'}>2. {intl.formatMessage({ id: 'auto.step_action' })}</span>
          </div>

          {step === 1 && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'auto.rule_name' })}</Label>
                <Input value={draft.name} onChange={(e) => patch({ name: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'auto.when' })}</Label>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={draft.trigger_type} onChange={(e) => patch({ trigger_type: e.target.value as TriggerType })}>
                  {TRIGGER_TYPES.map((t) => (
                    <option key={t} value={t}>{intl.formatMessage({ id: `auto.trig.${t}`, defaultMessage: t })}</option>
                  ))}
                </select>
              </div>

              {draft.trigger_type === 'event' && (
                <>
                  <Field label={intl.formatMessage({ id: 'auto.event_types_label' })}>
                    <ChipRow items={[...EVENT_TRIGGER_TYPES]} selected={draft.event_types} label={evLabel}
                      onToggle={(v) => patch({ event_types: toggle(draft.event_types, v) })} />
                  </Field>
                  {draft.event_types.includes('face') && (
                    <Field label={intl.formatMessage({ id: 'auto.identities_label' })}>
                      <MultiPick options={identities.map((i) => ({ id: i.id, label: i.name }))}
                        selected={draft.identity_ids} onChange={(ids) => patch({ identity_ids: ids })} />
                    </Field>
                  )}
                  <CameraPick label={intl.formatMessage({ id: 'auto.cameras_label' })} cameras={cameras}
                    selected={draft.camera_ids} onChange={(ids) => patch({ camera_ids: ids })} />
                  <ConditionBuilder draft={draft} patch={patch} evList={[...EVENT_TRIGGER_TYPES]} evLabel={evLabel} />
                </>
              )}

              {draft.trigger_type === 'object' && (
                <>
                  <Field label={intl.formatMessage({ id: 'auto.object_label' })}>
                    <ChipRow items={[...OBJECT_CLASSES]} selected={draft.classes} label={objLabel}
                      onToggle={(v) => patch({ classes: toggle(draft.classes, v) })} />
                  </Field>
                  <CameraPick label={intl.formatMessage({ id: 'auto.cameras_label' })} cameras={cameras}
                    selected={draft.camera_ids} onChange={(ids) => patch({ camera_ids: ids })} />
                </>
              )}

              {draft.trigger_type === 'system_event' && (
                <>
                  <Field label={intl.formatMessage({ id: 'auto.sysevent_label' })}>
                    <ChipRow items={[...SYSTEM_EVENTS]} selected={draft.system_events} label={sysLabel}
                      onToggle={(v) => patch({ system_events: toggle(draft.system_events, v) })} />
                  </Field>
                  <CameraPick label={intl.formatMessage({ id: 'auto.cameras_label' })} cameras={cameras}
                    selected={draft.camera_ids} onChange={(ids) => patch({ camera_ids: ids })} />
                  <Field label={intl.formatMessage({ id: 'auto.devices_label' })}>
                    <MultiPick options={targets.map((t) => ({ id: t.id, label: t.name }))}
                      selected={draft.device_ids} onChange={(ids) => patch({ device_ids: ids })} />
                  </Field>
                </>
              )}

              {draft.trigger_type === 'schedule' && <ScheduleBuilder draft={draft} patch={patch} />}

              {draft.trigger_type === 'incoming_webhook' && (
                <p className="rounded border border-border bg-secondary/40 p-2 text-xs text-muted-foreground">
                  {intl.formatMessage({ id: 'auto.incoming_hint' })}
                </p>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>{intl.formatMessage({ id: 'auto.actions' })}</Label>
                <Button variant="outline" size="sm" onClick={() => setActions([...draft.actions, { type: 'webhook', params: { method: 'POST', body_type: 'json' } }])}>
                  <Plus className="mr-1 h-3.5 w-3.5" />{intl.formatMessage({ id: 'auto.add_action' })}
                </Button>
              </div>
              {draft.actions.map((a, i) => (
                <ActionEditor key={i} action={a} cameras={cameras}
                  onChange={(next) => setActions(draft.actions.map((x, j) => (j === i ? next : x)))}
                  onRemove={() => setActions(draft.actions.filter((_, j) => j !== i))} />
              ))}
              {draft.actions.length === 0 && (
                <p className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                  {intl.formatMessage({ id: 'auto.no_actions' })}
                </p>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            {step === 1 ? (
              <Button disabled={!draft.name.trim()} onClick={() => setStep(2)}>{intl.formatMessage({ id: 'auto.next' })}</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setStep(1)}>{intl.formatMessage({ id: 'auto.back' })}</Button>
                <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate(draft)}>{intl.formatMessage({ id: 'common.save' })}</Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="space-y-1.5"><Label className="text-xs">{label}</Label>{children}</div>;
}

function ChipRow({ items, selected, onToggle, label }:
  { items: string[]; selected: string[]; onToggle: (v: string) => void; label?: (v: string) => string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((v) => (
        <button key={v} onClick={() => onToggle(v)}
          className={`rounded-full border px-2.5 py-1 text-xs ${selected.includes(v) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
          {label ? label(v) : v}
        </button>
      ))}
    </div>
  );
}

/** Checkbox-style multi-select rendered as a scrollable chip list. */
function MultiPick({ options, selected, onChange }:
  { options: { id: string; label: string }[]; selected: string[]; onChange: (ids: string[]) => void }) {
  const intl = useIntl();
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  if (options.length === 0) {
    return <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'common.none', defaultMessage: '—' })}</p>;
  }
  return (
    <div className="flex max-h-32 flex-wrap gap-1.5 overflow-auto rounded border border-border p-2">
      {options.map((o) => (
        <button key={o.id} onClick={() => toggle(o.id)}
          className={`rounded-full border px-2.5 py-1 text-xs ${selected.includes(o.id) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function CameraPick({ label, cameras, selected, onChange }:
  { label: string; cameras: { id: string; name: string }[]; selected: string[]; onChange: (ids: string[]) => void }) {
  return (
    <Field label={label}>
      <MultiPick options={cameras.map((c) => ({ id: String(c.id), label: c.name }))} selected={selected} onChange={onChange} />
    </Field>
  );
}

function ScheduleBuilder({ draft, patch }: { draft: Draft; patch: (p: Partial<Draft>) => void }) {
  const intl = useIntl();
  const repeats: ScheduleRepeat[] = ['daily', 'weekdays', 'weekends', 'custom'];
  const toggleDay = (d: number) =>
    patch({ sched_days: draft.sched_days.includes(d) ? draft.sched_days.filter((x) => x !== d) : [...draft.sched_days, d] });
  return (
    <div className="space-y-3">
      <Field label={intl.formatMessage({ id: 'auto.sched_repeat' })}>
        <div className="flex flex-wrap gap-1.5">
          {repeats.map((r) => (
            <button key={r} onClick={() => patch({ sched_repeat: r })}
              className={`rounded-full border px-2.5 py-1 text-xs ${draft.sched_repeat === r ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
              {intl.formatMessage({ id: `auto.sched_${r}` })}
            </button>
          ))}
        </div>
      </Field>
      {draft.sched_repeat === 'custom' && (
        <div className="flex flex-wrap gap-1.5">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <button key={d} onClick={() => toggleDay(d)}
              className={`h-8 w-8 rounded-full border text-xs ${draft.sched_days.includes(d) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
              {intl.formatMessage({ id: `dow.${d}` })}
            </button>
          ))}
        </div>
      )}
      <Field label={intl.formatMessage({ id: 'auto.sched_time' })}>
        <div className="flex items-center gap-1">
          <select className="h-9 rounded border border-input bg-background px-2 text-sm"
            value={draft.sched_hour} onChange={(e) => patch({ sched_hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, '0')}</option>)}
          </select>
          <span>:</span>
          <select className="h-9 rounded border border-input bg-background px-2 text-sm"
            value={draft.sched_minute} onChange={(e) => patch({ sched_minute: Number(e.target.value) })}>
            {[0, 5, 10, 15, 20, 30, 40, 45, 50].map((m) => <option key={m} value={m}>{String(m).padStart(2, '0')}</option>)}
          </select>
        </div>
      </Field>
    </div>
  );
}

/** AND/OR builder: require other events to also occur (AND) — or any of them (OR) — within
 * a time window. Plain-language framing; maps to the rule's `correlate` condition. */
function ConditionBuilder({ draft, patch, evList, evLabel }:
  { draft: Draft; patch: (p: Partial<Draft>) => void; evList: string[]; evLabel: (v: string) => string }) {
  const intl = useIntl();
  const add = () => patch({ cond_events: [...draft.cond_events, { type: evList[0], camera: 'same' }] });
  const update = (i: number, e: Partial<CondEvent>) =>
    patch({ cond_events: draft.cond_events.map((c, j) => (j === i ? { ...c, ...e } : c)) });
  const remove = (i: number) => patch({ cond_events: draft.cond_events.filter((_, j) => j !== i) });

  return (
    <div className="space-y-2 rounded border border-border p-2.5">
      <div className="flex items-center justify-between">
        <Label className="text-xs">{intl.formatMessage({ id: 'auto.cond_title' })}</Label>
        <Button variant="outline" size="sm" className="h-7" onClick={add}>
          <Plus className="mr-1 h-3.5 w-3.5" />{intl.formatMessage({ id: 'auto.add_condition' })}
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">{intl.formatMessage({ id: 'auto.cond_help' })}</p>
      {draft.cond_events.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <div className="flex overflow-hidden rounded border border-border">
              {(['all', 'any'] as const).map((m) => (
                <button key={m} onClick={() => patch({ cond_mode: m })}
                  className={`px-2.5 py-1 ${draft.cond_mode === m ? 'bg-primary/10 text-primary' : 'text-muted-foreground'}`}>
                  {intl.formatMessage({ id: m === 'all' ? 'auto.cond_all' : 'auto.cond_any' })}
                </button>
              ))}
            </div>
            <span className="text-muted-foreground">·</span>
            <input type="number" min={2} className="h-8 w-16 rounded border border-input bg-background px-2"
              value={draft.cond_window_s} onChange={(e) => patch({ cond_window_s: Number(e.target.value) })} />
            <span className="text-muted-foreground">{intl.formatMessage({ id: 'auto.within_seconds' })}</span>
          </div>
          {draft.cond_events.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <select className="h-8 flex-1 rounded border border-input bg-background px-2 text-xs"
                value={c.type} onChange={(e) => update(i, { type: e.target.value })}>
                {evList.map((t) => <option key={t} value={t}>{evLabel(t)}</option>)}
              </select>
              <select className="h-8 rounded border border-input bg-background px-2 text-xs"
                value={c.camera} onChange={(e) => update(i, { camera: e.target.value as 'same' | 'any' })}>
                <option value="same">{intl.formatMessage({ id: 'auto.same_camera' })}</option>
                <option value="any">{intl.formatMessage({ id: 'auto.any_camera_short' })}</option>
              </select>
              <Button variant="ghost" size="icon" onClick={() => remove(i)}><Trash2 className="h-3.5 w-3.5 text-red-400" /></Button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

const SELECT_CLASS = 'h-10 w-full rounded border border-input bg-background px-2 text-sm';

function ActionEditor({ action, cameras, onChange, onRemove }: {
  action: RuleAction;
  cameras: { id: string; name: string }[];
  onChange: (a: RuleAction) => void;
  onRemove: () => void;
}) {
  const intl = useIntl();
  const params = action.params ?? {};
  const setParam = (k: string, v: unknown) => onChange({ ...action, params: { ...params, [k]: v } });
  const method = String(params.method ?? 'POST');

  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex items-end gap-2">
        <Field label={intl.formatMessage({ id: 'auto.action_kind' })}>
          <select className={SELECT_CLASS}
            value={action.type} onChange={(e) => onChange({ type: e.target.value as ActionType, params: {} })}>
            {ACTION_TYPES.map((t) => <option key={t} value={t}>{intl.formatMessage({ id: `auto.act.${t}`, defaultMessage: t })}</option>)}
          </select>
        </Field>
        <Button variant="ghost" size="icon" className="shrink-0" onClick={onRemove}>
          <Trash2 className="h-4 w-4 text-red-400" />
        </Button>
      </div>

      {action.type === 'webhook' && (
        <>
          <Field label="URL">
            <Input placeholder="https://…" value={String(params.url ?? '')} onChange={(e) => setParam('url', e.target.value)} />
          </Field>
          <div className={method === 'GET' ? '' : 'grid grid-cols-2 gap-2'}>
            <Field label={intl.formatMessage({ id: 'auto.http_method' })}>
              <select className={SELECT_CLASS} value={method} onChange={(e) => setParam('method', e.target.value)}>
                {['POST', 'GET', 'PUT'].map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </Field>
            {/* GET has no body — only POST/PUT pick a body format */}
            {method !== 'GET' && (
              <Field label={intl.formatMessage({ id: 'auto.body_type' })}>
                <select className={SELECT_CLASS} value={String(params.body_type ?? 'json')} onChange={(e) => setParam('body_type', e.target.value)}>
                  {['json', 'form', 'urlencoded', 'none'].map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </Field>
            )}
          </div>
          <Field label={intl.formatMessage({ id: 'auto.auth_label' })}>
            <WebhookAuth params={params} setParam={setParam} />
          </Field>
          <Field label={intl.formatMessage({ id: 'auto.headers_label' })}>
            <textarea className="h-16 w-full rounded border border-input bg-background p-2 font-mono text-xs"
              placeholder={intl.formatMessage({ id: 'auto.headers_json' })}
              value={typeof params.headers === 'string' ? params.headers : JSON.stringify(params.headers ?? {}, null, 0)}
              onChange={(e) => {
                try { setParam('headers', e.target.value ? JSON.parse(e.target.value) : {}); }
                catch { setParam('headers', e.target.value); }
              }} />
          </Field>
        </>
      )}

      {action.type === 'sms' && (
        <Field label={intl.formatMessage({ id: 'auto.sms_to' })}>
          <Input placeholder="+15550001111" value={String(params.to ?? '')} onChange={(e) => setParam('to', e.target.value)} />
        </Field>
      )}

      {action.type === 'email' && (
        <Field label={intl.formatMessage({ id: 'auto.email_to' })}>
          <Input type="email" placeholder="someone@example.com" value={String(params.to ?? '')} onChange={(e) => setParam('to', e.target.value)} />
        </Field>
      )}

      {action.type === 'push' && (
        <>
          <Field label={intl.formatMessage({ id: 'auto.push_title' })}>
            <Input placeholder={intl.formatMessage({ id: 'auto.push_title_ph' })} value={String(params.title ?? '')} onChange={(e) => setParam('title', e.target.value)} />
          </Field>
          <Field label={intl.formatMessage({ id: 'auto.push_message' })}>
            <Input placeholder={intl.formatMessage({ id: 'auto.push_message_ph' })} value={String(params.message ?? '')} onChange={(e) => setParam('message', e.target.value)} />
          </Field>
        </>
      )}

      {(action.type === 'camera_enable' || action.type === 'camera_disable') && (
        <Field label={intl.formatMessage({ id: 'auto.camera_label' })}>
          <select className={SELECT_CLASS} value={String(params.camera_id ?? '')} onChange={(e) => setParam('camera_id', e.target.value)}>
            <option value="">{intl.formatMessage({ id: 'auto.camera_id_trigger' })}</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
      )}
    </div>
  );
}

function WebhookAuth({ params, setParam }: { params: Record<string, unknown>; setParam: (k: string, v: unknown) => void }) {
  const intl = useIntl();
  const auth = (params.auth as Record<string, unknown>) ?? { type: 'none' };
  const setAuth = (k: string, v: unknown) => setParam('auth', { ...auth, [k]: v });
  const type = String(auth.type ?? 'none');
  return (
    <div className="space-y-2">
      <select className={SELECT_CLASS} value={type} onChange={(e) => setAuth('type', e.target.value)}>
        {['none', 'basic', 'bearer', 'header'].map((t) => (
          <option key={t} value={t}>{intl.formatMessage({ id: `auto.auth.${t}`, defaultMessage: t })}</option>
        ))}
      </select>
      {type === 'basic' && (
        <div className="grid grid-cols-2 gap-2">
          <Input placeholder="user" value={String(auth.username ?? '')} onChange={(e) => setAuth('username', e.target.value)} />
          <Input type="password" placeholder="pass" value={String(auth.password ?? '')} onChange={(e) => setAuth('password', e.target.value)} />
        </div>
      )}
      {type === 'bearer' && (
        <Input type="password" placeholder="token" value={String(auth.token ?? '')} onChange={(e) => setAuth('token', e.target.value)} />
      )}
      {type === 'header' && (
        <div className="grid grid-cols-2 gap-2">
          <Input placeholder="X-Api-Key" value={String(auth.header_name ?? '')} onChange={(e) => setAuth('header_name', e.target.value)} />
          <Input type="password" placeholder="value" value={String(auth.header_value ?? '')} onChange={(e) => setAuth('header_value', e.target.value)} />
        </div>
      )}
    </div>
  );
}
