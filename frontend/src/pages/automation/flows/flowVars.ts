// Upstream-variable discovery: what {{variables}} a node can actually see, computed by
// walking the graph backwards from that node. Trigger vars depend on the trigger node's
// selected sources; every executed ancestor contributes its nodes.<id>.* outputs.
import type { Edge } from '@xyflow/react';

import type { EditorNode } from '@/pages/automation/flows/flowNodes';
import type { ConditionClause, FlowNodeType, TriggerSourceType } from '@/types/flow';

export interface VarOption {
  path: string;                        // template path, e.g. trigger.score / nodes.<id>.http_status
  /** clause preset for the condition picker — field-based when the server evaluator
   *  supports it natively, otherwise a custom-left template compare */
  clause: Pick<ConditionClause, 'field' | 'left'>;
  labelId?: string;                    // optional i18n suffix (flow.condfield.*)
}

const fieldVar = (path: string, field: string, labelId?: string): VarOption =>
  ({ path, clause: { field }, labelId });
const tplVar = (path: string): VarOption =>
  ({ path, clause: { field: 'custom', left: `{{${path}}}` } });

/** Always present regardless of source type. */
const COMMON: VarOption[] = [
  fieldVar('trigger.type', 'type', 'flow.condfield.type'),
  fieldVar('trigger.camera_id', 'camera_id', 'flow.condfield.camera_id'),
  tplVar('trigger.camera_name'),
  tplVar('trigger.ts'),
];

const BY_SOURCE: Partial<Record<TriggerSourceType, VarOption[]>> = {
  event: [
    fieldVar('trigger.subtype', 'subtype', 'flow.condfield.subtype'),
    fieldVar('trigger.score', 'score', 'flow.condfield.score'),
    fieldVar('trigger.identity', 'identity', 'flow.condfield.identity'),
    tplVar('trigger.event_id'),
  ],
  object: [
    fieldVar('trigger.object_class', 'object_class', 'flow.condfield.object_class'),
    fieldVar('trigger.score', 'score', 'flow.condfield.score'),
    tplVar('trigger.event_id'),
  ],
  system_event: [
    fieldVar('trigger.device_id', 'device_id', 'flow.condfield.device_id'),
  ],
  incoming_webhook: [
    tplVar('trigger.context.body.key'),
    tplVar('trigger.context.query.key'),
  ],
  manual: [tplVar('trigger.context.key')],
};

/** Outputs each node type contributes to ctx.nodes.<id>.* once it has run. */
const NODE_OUTPUTS: Partial<Record<FlowNodeType, string[]>> = {
  condition: ['result'],
  delay: ['slept_s'],
  webhook: ['status', 'http_status', 'latency_ms'],
  push: ['status', 'pushed'],
  email: ['status'],
  sms: ['status'],
  record: ['status', 'recording_id', 'start_ts'],
  camera_enable: ['status', 'camera_id', 'enabled'],
  camera_disable: ['status', 'camera_id', 'enabled'],
  speaker: ['status'],
  io: ['status'],
};

/** IDs of every node that can precede `nodeId` (reverse reachability). */
export function upstreamNodeIds(nodeId: string, edges: Edge[]): Set<string> {
  const sourcesOf = new Map<string, string[]>();
  for (const e of edges) {
    if (!sourcesOf.has(e.target)) sourcesOf.set(e.target, []);
    sourcesOf.get(e.target)!.push(e.source);
  }
  const seen = new Set<string>();
  const queue = [...(sourcesOf.get(nodeId) ?? [])];
  while (queue.length) {
    const id = queue.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    queue.push(...(sourcesOf.get(id) ?? []));
  }
  return seen;
}

/** Variables visible to `nodeId`, given the current canvas. Empty ⇒ not connected yet. */
export function upstreamVars(nodeId: string, nodes: EditorNode[], edges: Edge[]): VarOption[] {
  const ancestors = upstreamNodeIds(nodeId, edges);
  if (!ancestors.size) return [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: VarOption[] = [];
  const seen = new Set<string>();
  const push = (v: VarOption) => {
    if (!seen.has(v.path)) {
      seen.add(v.path);
      out.push(v);
    }
  };

  for (const id of ancestors) {
    const n = byId.get(id);
    if (!n) continue;
    if (n.type === 'trigger') {
      COMMON.forEach(push);
      for (const s of n.data.sources ?? []) {
        (BY_SOURCE[s.trigger_type] ?? []).forEach(push);
      }
    } else {
      for (const key of NODE_OUTPUTS[n.type as FlowNodeType] ?? []) {
        push(tplVar(`nodes.${id}.${key}`));
      }
    }
  }
  return out;
}
