// Custom React Flow nodes: trigger (source only), condition (true/false), action (ok/err).
// Run-replay coloring rides on data.runStatus / data.runDurationMs injected by the editor.
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import { AlertCircle, Check, X } from 'lucide-react';
import { useIntl } from 'react-intl';

import { NODE_META, RUN_STATUS_RING } from '@/pages/automation/flows/flowCatalog';
import type { FlowNodeData, FlowNodeType } from '@/types/flow';

export type EditorNode = Node<FlowNodeData & {
  runStatus?: string;
  runDurationMs?: number | null;
  runError?: string | null;
  runMode?: boolean;
}, FlowNodeType>;

const HANDLE = '!h-2.5 !w-2.5 !rounded-full !border-2 !border-background';

function summary(type: FlowNodeType, data: EditorNode['data'], fm: (id: string) => string): string {
  switch (type) {
    case 'trigger': {
      const srcs = data.sources ?? [];
      if (!srcs.length) return fm('flow.node.trigger.empty');
      return srcs.map((s) => fm(`flow.source.${s.trigger_type}`)).join(' · ');
    }
    case 'condition':
      return `${fm(`flow.cond.${data.mode === 'any' ? 'any' : 'all'}`)} · ${(data.clauses ?? []).length}`;
    case 'delay':
      return `${data.seconds ?? 0}s`;
    case 'webhook':
      return String(data.url || '—');
    case 'push':
      return String(data.title || fm('flow.node.push'));
    case 'email':
    case 'sms':
      return String(data.to || '—');
    case 'record':
      return `${data.camera_id ? `#${data.camera_id}` : fm('flow.triggerCamera')} · ${data.duration_s ?? 60}s`;
    case 'camera_enable':
    case 'camera_disable':
      return data.camera_id ? `#${data.camera_id}` : fm('flow.triggerCamera');
    case 'speaker':
    case 'io':
      return data.target_id ? `#${data.target_id}` : '—';
    default:
      return '';
  }
}

function NodeShell({ node, children }: { node: NodeProps<EditorNode>; children?: React.ReactNode }) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const type = node.type as FlowNodeType;
  const meta = NODE_META[type];
  const Icon = meta.icon;
  const { runStatus, runMode } = node.data;
  const ring = runStatus ? RUN_STATUS_RING[runStatus] ?? '' : '';
  const dim = runMode && !runStatus ? 'opacity-40' : '';

  return (
    <div className={`w-52 rounded border bg-white p-2.5 transition-all ${node.selected ? 'border-primary ring-1 ring-primary' : 'border-border'} ${ring} ${dim}`}>
      <div className="flex items-center gap-2">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded ${meta.chip}`}>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-foreground">
            {String(node.data.label || fm(`flow.node.${type}`))}
          </p>
          <p className="truncate text-[10px] text-muted-foreground">{summary(type, node.data, fm)}</p>
        </div>
        {runStatus === 'success' && <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />}
        {runStatus === 'failed' && <X className="h-3.5 w-3.5 shrink-0 text-red-600" />}
        {runStatus === 'skipped' && <AlertCircle className="h-3.5 w-3.5 shrink-0 text-amber-500" />}
      </div>
      {runStatus && node.data.runDurationMs != null && (
        <p className="mt-1 text-right text-[10px] text-muted-foreground">{node.data.runDurationMs}ms</p>
      )}
      {runStatus === 'failed' && node.data.runError && (
        <p className="mt-1 truncate text-[10px] text-red-600" title={String(node.data.runError)}>
          {String(node.data.runError)}
        </p>
      )}
      {children}
    </div>
  );
}

export function TriggerFlowNode(props: NodeProps<EditorNode>) {
  return (
    <NodeShell node={props}>
      <Handle type="source" position={Position.Right} id="out" className={`${HANDLE} !bg-amber-500`} />
    </NodeShell>
  );
}

export function ConditionFlowNode(props: NodeProps<EditorNode>) {
  return (
    <NodeShell node={props}>
      <Handle type="target" position={Position.Left} className={`${HANDLE} !bg-slate-400`} />
      <Handle type="source" position={Position.Right} id="true" style={{ top: '35%' }}
        className={`${HANDLE} !bg-emerald-500`} />
      <Handle type="source" position={Position.Right} id="false" style={{ top: '75%' }}
        className={`${HANDLE} !bg-red-500`} />
      <span className="pointer-events-none absolute -right-7 top-[35%] -translate-y-1/2 text-[9px] font-semibold text-emerald-600">T</span>
      <span className="pointer-events-none absolute -right-7 top-[75%] -translate-y-1/2 text-[9px] font-semibold text-red-500">F</span>
    </NodeShell>
  );
}

export function ActionFlowNode(props: NodeProps<EditorNode>) {
  return (
    <NodeShell node={props}>
      <Handle type="target" position={Position.Left} className={`${HANDLE} !bg-slate-400`} />
      <Handle type="source" position={Position.Right} id="ok" style={{ top: '35%' }}
        className={`${HANDLE} !bg-emerald-500`} />
      <Handle type="source" position={Position.Right} id="err" style={{ top: '75%' }}
        className={`${HANDLE} !bg-red-500`} />
      <span className="pointer-events-none absolute -right-8 top-[35%] -translate-y-1/2 text-[9px] font-semibold text-emerald-600">OK</span>
      <span className="pointer-events-none absolute -right-8 top-[75%] -translate-y-1/2 text-[9px] font-semibold text-red-500">ERR</span>
    </NodeShell>
  );
}

export const flowNodeTypes = {
  trigger: TriggerFlowNode,
  condition: ConditionFlowNode,
  delay: ActionFlowNode,
  webhook: ActionFlowNode,
  push: ActionFlowNode,
  email: ActionFlowNode,
  sms: ActionFlowNode,
  record: ActionFlowNode,
  camera_enable: ActionFlowNode,
  camera_disable: ActionFlowNode,
  speaker: ActionFlowNode,
  io: ActionFlowNode,
};
