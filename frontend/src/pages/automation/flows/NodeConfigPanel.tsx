// Right-side config panel for the selected node — click-click forms per node type.
import type { Edge } from '@xyflow/react';
import { Copy, Plus, Trash2 } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NODE_META } from '@/pages/automation/flows/flowCatalog';
import type { EditorNode } from '@/pages/automation/flows/flowNodes';
import { upstreamVars, type VarOption } from '@/pages/automation/flows/flowVars';
import type { ActionTarget } from '@/types/p5';
import type { Camera } from '@/types/axp';
import {
  CONDITION_OPS,
  type ConditionClause,
  type FlowNodeData,
  type FlowNodeType,
  type TriggerSource,
  type TriggerSourceType,
} from '@/types/flow';

const EVENT_TRIGGER_TYPES = ['motion', 'object', 'intrusion', 'tamper', 'loitering', 'line_crossing',
  'doorbell_call', 'audio_class', 'face', 'lpr'];
const OBJECT_CLASSES = ['person', 'car', 'truck', 'bus', 'dog', 'cat'];
const SYSTEM_EVENTS = ['camera_online', 'camera_offline', 'camera_config_changed', 'camera_motion',
  'doorbell_ring', 'io_input_on', 'io_input_off', 'device_online', 'device_offline'];
const SOURCE_TYPES: TriggerSourceType[] = ['event', 'object', 'system_event', 'schedule', 'incoming_webhook', 'manual'];

/** '5' → 5, 'a,b' (for in/not_in) → ['a','b'] — matches what the server ops expect. */
function coerce(raw: string, op: string): unknown {
  if (op === 'in' || op === 'not_in') {
    return raw.split(',').map((s) => coerce(s.trim(), 'eq'));
  }
  return /^-?\d+(\.\d+)?$/.test(raw.trim()) ? Number(raw) : raw;
}
function uncoerce(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(',');
  return v == null ? '' : String(v);
}

interface Props {
  node: EditorNode;
  nodes: EditorNode[];
  edges: Edge[];
  cameras: Camera[];
  targets: ActionTarget[];
  incomingUrl: string;
  onChange: (patch: Partial<FlowNodeData>) => void;
  onDelete: () => void;
}

export function NodeConfigPanel({ node, nodes, edges, cameras, targets, incomingUrl, onChange, onDelete }: Props) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const type = node.type as FlowNodeType;
  const Icon = NODE_META[type].icon;
  const d = node.data;
  // variables actually reachable from upstream nodes — drives the condition picker + hints
  const vars = useMemo(() => upstreamVars(node.id, nodes, edges), [node.id, nodes, edges]);

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center gap-2">
        <span className={`flex h-7 w-7 items-center justify-center rounded ${NODE_META[type].chip}`}>
          <Icon className="h-4 w-4" />
        </span>
        <h3 className="flex-1 text-sm font-semibold text-foreground">{fm(`flow.node.${type}`)}</h3>
        <Button variant="ghost" size="icon" onClick={onDelete} title={fm('flow.deleteNode')}>
          <Trash2 className="h-4 w-4 text-muted-foreground" />
        </Button>
      </div>

      <Field label={fm('flow.field.label')}>
        <Input value={String(d.label ?? '')} placeholder={fm(`flow.node.${type}`)}
          onChange={(e) => onChange({ label: e.target.value })} />
      </Field>

      {type === 'trigger' && (
        <TriggerForm d={d} cameras={cameras} incomingUrl={incomingUrl} onChange={onChange} />
      )}
      {type === 'condition' && <ConditionForm d={d} vars={vars} onChange={onChange} />}
      {type === 'delay' && (
        <Field label={fm('flow.field.seconds')}>
          <Input type="number" min={0} max={60} value={d.seconds ?? 5}
            onChange={(e) => onChange({ seconds: Number(e.target.value) })} />
        </Field>
      )}
      {type === 'webhook' && <WebhookForm d={d} onChange={onChange} />}
      {type === 'push' && (
        <>
          <Field label={fm('flow.field.title')}>
            <Input value={String(d.title ?? '')} onChange={(e) => onChange({ title: e.target.value })} />
          </Field>
          <Field label={fm('flow.field.message')}>
            <textarea value={String(d.message ?? '')} rows={3}
              onChange={(e) => onChange({ message: e.target.value })}
              className="w-full rounded border border-border bg-transparent px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
          </Field>
        </>
      )}
      {(type === 'email' || type === 'sms') && (
        <Field label={fm(type === 'email' ? 'flow.field.emailTo' : 'flow.field.smsTo')}>
          <Input value={String(d.to ?? '')} onChange={(e) => onChange({ to: e.target.value })}
            placeholder={type === 'email' ? 'ops@example.com' : '+821012345678'} />
        </Field>
      )}
      {(type === 'record' || type === 'camera_enable' || type === 'camera_disable') && (
        <>
          <Field label={fm('flow.field.camera')}>
            <select value={String(d.camera_id ?? '')} onChange={(e) => onChange({ camera_id: e.target.value })}
              className="w-full rounded border border-border bg-transparent px-2 py-1.5 text-sm text-foreground">
              <option value="">{fm('flow.triggerCamera')}</option>
              {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          {type === 'record' && (
            <Field label={fm('flow.field.duration')}>
              <Input type="number" min={5} max={86400} value={d.duration_s ?? 60}
                onChange={(e) => onChange({ duration_s: Number(e.target.value) })} />
            </Field>
          )}
        </>
      )}
      {(type === 'speaker' || type === 'io') && (
        <Field label={fm('flow.field.target')}>
          <select value={String(d.target_id ?? '')} onChange={(e) => onChange({ target_id: e.target.value })}
            className="w-full rounded border border-border bg-transparent px-2 py-1.5 text-sm text-foreground">
            <option value="">—</option>
            {targets.filter((t) => t.type === type).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </Field>
      )}

      {type !== 'trigger' && type !== 'condition' && (
        <div className="rounded border border-border bg-secondary/50 p-2">
          <p className="mb-1 text-[11px] font-medium text-muted-foreground">{fm('flow.varsHint')}</p>
          {vars.length ? (
            <div className="flex flex-wrap gap-1">
              {vars.map((v) => (
                <code key={v.path} className="cursor-pointer rounded bg-secondary px-1 py-0.5 text-[10px] text-foreground"
                  onClick={() => { void navigator.clipboard?.writeText(`{{${v.path}}}`); toast.success(fm('flow.varCopied')); }}>
                  {`{{${v.path}}}`}
                </code>
              ))}
            </div>
          ) : (
            <p className="text-[10px] text-muted-foreground">{fm('flow.vars.connectHint')}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── trigger ───────────────────────────────────────────────────────────────────
function TriggerForm({ d, cameras, incomingUrl, onChange }:
  { d: FlowNodeData; cameras: Camera[]; incomingUrl: string; onChange: (p: Partial<FlowNodeData>) => void }) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const sources = d.sources ?? [];
  const setSource = (i: number, patch: Partial<TriggerSource>) =>
    onChange({ sources: sources.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{fm('flow.trigger.help')}</p>
      {sources.map((s, i) => (
        <div key={i} className="space-y-2 rounded border border-border p-2.5">
          <div className="flex items-center gap-2">
            <select value={s.trigger_type} className="flex-1 rounded border border-border bg-transparent px-2 py-1.5 text-sm text-foreground"
              onChange={(e) => setSource(i, { trigger_type: e.target.value as TriggerSourceType })}>
              {SOURCE_TYPES.map((t) => <option key={t} value={t}>{fm(`flow.source.${t}`)}</option>)}
            </select>
            <Button variant="ghost" size="icon"
              onClick={() => onChange({ sources: sources.filter((_, j) => j !== i) })}>
              <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
            </Button>
          </div>

          {s.trigger_type === 'event' && (
            <ChipRow items={EVENT_TRIGGER_TYPES} selected={s.event_types ?? []}
              onToggle={(v) => setSource(i, { event_types: toggle(s.event_types ?? [], v) })}
              label={(v) => intl.formatMessage({ id: `event.type.${v}`, defaultMessage: v })} />
          )}
          {s.trigger_type === 'object' && (
            <>
              <ChipRow items={OBJECT_CLASSES} selected={s.classes ?? []}
                onToggle={(v) => setSource(i, { classes: toggle(s.classes ?? [], v) })}
                label={(v) => intl.formatMessage({ id: `objclass.${v}`, defaultMessage: v })} />
              <Field label={fm('flow.field.minConfidence')}>
                <Input type="number" min={0} max={100} value={s.min_confidence ?? 60}
                  onChange={(e) => setSource(i, { min_confidence: Number(e.target.value) })} />
              </Field>
            </>
          )}
          {s.trigger_type === 'system_event' && (
            <ChipRow items={SYSTEM_EVENTS} selected={s.event_types ?? []}
              onToggle={(v) => setSource(i, { event_types: toggle(s.event_types ?? [], v) })}
              label={(v) => intl.formatMessage({ id: `sysevent.${v}`, defaultMessage: v })} />
          )}
          {s.trigger_type === 'schedule' && (
            <Field label={fm('flow.field.cron')}>
              <Input value={s.cron ?? ''} placeholder="30 9 * * 1-5"
                onChange={(e) => setSource(i, { cron: e.target.value })} />
            </Field>
          )}
          {s.trigger_type === 'incoming_webhook' && (
            <div className="flex items-center gap-1 rounded bg-secondary px-2 py-1.5">
              <code className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">{incomingUrl}</code>
              <button onClick={() => { void navigator.clipboard?.writeText(incomingUrl); toast.success(fm('auto.hook_copied')); }}>
                <Copy className="h-3 w-3 text-muted-foreground" />
              </button>
            </div>
          )}
          {(s.trigger_type === 'event' || s.trigger_type === 'object') && (
            <Field label={fm('flow.field.cameras')}>
              <ChipRow items={cameras.map((c) => c.id)} selected={s.camera_ids ?? []}
                onToggle={(v) => setSource(i, { camera_ids: toggle(s.camera_ids ?? [], v) })}
                label={(id) => cameras.find((c) => c.id === id)?.name ?? id} />
            </Field>
          )}
        </div>
      ))}
      <Button variant="outline" size="sm" className="w-full"
        onClick={() => onChange({ sources: [...sources, { trigger_type: 'event', event_types: ['motion'] }] })}>
        <Plus className="mr-1 h-3.5 w-3.5" />{fm('flow.trigger.addSource')}
      </Button>
    </div>
  );
}

// ── condition ─────────────────────────────────────────────────────────────────
const MANUAL = '__manual__';

/** select value for the clause's current variable: matching upstream var path, or manual */
function clauseVarKey(c: ConditionClause, vars: VarOption[]): string {
  const hit = vars.find((v) =>
    v.clause.field === 'custom'
      ? c.field === 'custom' && c.left === v.clause.left
      : c.field === v.clause.field);
  return hit ? hit.path : MANUAL;
}

function ConditionForm({ d, vars, onChange }:
  { d: FlowNodeData; vars: VarOption[]; onChange: (p: Partial<FlowNodeData>) => void }) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const clauses = d.clauses ?? [];
  const setClause = (i: number, patch: Partial<ConditionClause>) =>
    onChange({ clauses: clauses.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  const varLabel = (v: VarOption) =>
    v.labelId ? `${fm(v.labelId)} — ${v.path}` : v.path;
  const firstVar: Partial<ConditionClause> = vars.length
    ? { ...vars[0].clause } : { field: 'custom', left: '' };

  return (
    <div className="space-y-3">
      <Field label={fm('flow.cond.mode')}>
        <div className="flex gap-1">
          {(['all', 'any'] as const).map((m) => (
            <button key={m} onClick={() => onChange({ mode: m })}
              className={`flex-1 rounded border px-2 py-1 text-xs ${(d.mode ?? 'all') === m ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
              {fm(`flow.cond.${m}`)}
            </button>
          ))}
        </div>
      </Field>
      {!vars.length && (
        <p className="rounded border border-border bg-secondary/50 p-2 text-[10px] text-muted-foreground">
          {fm('flow.vars.connectHint')}
        </p>
      )}
      {clauses.map((c, i) => (
        <div key={i} className="space-y-2 rounded border border-border p-2.5">
          <div className="flex items-center gap-2">
            <select value={clauseVarKey(c, vars)}
              className="min-w-0 flex-1 rounded border border-border bg-transparent px-2 py-1 text-xs text-foreground"
              onChange={(e) => {
                const v = vars.find((x) => x.path === e.target.value);
                setClause(i, v
                  ? { field: v.clause.field, left: v.clause.field === 'custom' ? v.clause.left : undefined }
                  : { field: 'custom', left: c.left ?? '' });
              }}>
              {vars.map((v) => <option key={v.path} value={v.path}>{varLabel(v)}</option>)}
              <option value={MANUAL}>{fm('flow.cond.manualVar')}</option>
            </select>
            <Button variant="ghost" size="icon"
              onClick={() => onChange({ clauses: clauses.filter((_, j) => j !== i) })}>
              <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
            </Button>
          </div>
          {c.field === 'custom' && (
            <Input value={c.left ?? ''} placeholder="{{trigger.context.body.key}}"
              onChange={(e) => setClause(i, { left: e.target.value })} />
          )}
          <div className="flex gap-2">
            <select value={c.op} className="rounded border border-border bg-transparent px-2 py-1 text-xs text-foreground"
              onChange={(e) => setClause(i, { op: e.target.value as ConditionClause['op'], value: coerce(uncoerce(c.value), e.target.value) })}>
              {CONDITION_OPS.map((o) => <option key={o} value={o}>{fm(`flow.op.${o}`)}</option>)}
            </select>
            <Input value={uncoerce(c.value)} placeholder={fm('flow.cond.valuePh')}
              onChange={(e) => setClause(i, { value: coerce(e.target.value, c.op) })} />
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm" className="w-full"
        onClick={() => onChange({ clauses: [...clauses, { op: 'eq', value: '', ...firstVar } as ConditionClause] })}>
        <Plus className="mr-1 h-3.5 w-3.5" />{fm('flow.cond.addClause')}
      </Button>
    </div>
  );
}

// ── webhook ───────────────────────────────────────────────────────────────────
function WebhookForm({ d, onChange }:
  { d: FlowNodeData; onChange: (p: Partial<FlowNodeData>) => void }) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  return (
    <div className="space-y-3">
      <Field label="URL">
        <Input value={String(d.url ?? '')} placeholder="https://…"
          onChange={(e) => onChange({ url: e.target.value })} />
      </Field>
      <Field label={fm('flow.field.method')}>
        <div className="flex gap-1">
          {['GET', 'POST', 'PUT'].map((m) => (
            <button key={m} onClick={() => onChange({ method: m })}
              className={`flex-1 rounded border px-2 py-1 text-xs ${(d.method ?? 'POST') === m ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
              {m}
            </button>
          ))}
        </div>
      </Field>
      <KvEditor label={fm('flow.field.headers')} value={(d.headers ?? {}) as Record<string, string>}
        onChange={(headers) => onChange({ headers })} />
      <KvEditor label={fm('flow.field.body')} value={(d.body ?? {}) as Record<string, string>}
        onChange={(body) => onChange({ body })} hint={fm('flow.field.bodyHint')} />
    </div>
  );
}

/** Key/value rows editor (headers, webhook body, io params). */
function KvEditor({ label, value, onChange, hint }:
  { label: string; value: Record<string, unknown>; onChange: (v: Record<string, string>) => void; hint?: string }) {
  // empty keys survive while typing; the editor strips them from the graph at save time
  const entries = Object.entries(value).map(([k, v]) => [k, String(v ?? '')] as [string, string]);
  const write = (rows: [string, string][]) => onChange(Object.fromEntries(rows));
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
      {entries.map(([k, v], i) => (
        <div key={i} className="flex gap-1">
          <Input value={k} className="w-2/5" placeholder="key"
            onChange={(e) => write(entries.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
          <Input value={v} placeholder="value"
            onChange={(e) => write(entries.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
          <Button variant="ghost" size="icon" onClick={() => write(entries.filter((_, j) => j !== i))}>
            <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
      ))}
      <Button variant="outline" size="sm" className="w-full"
        onClick={() => onChange({ ...(Object.fromEntries(entries)), '': '' } as Record<string, string>)}>
        <Plus className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

// ── tiny shared pieces ────────────────────────────────────────────────────────
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
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

function toggle(xs: string[], v: string): string[] {
  return xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v];
}
