// Visual automation flows (n8n-style node graph) DTOs — mirror server/model/flow.py.

export type FlowNodeType =
  | 'trigger' | 'condition' | 'delay'
  | 'webhook' | 'push' | 'email' | 'sms' | 'record'
  | 'camera_enable' | 'camera_disable' | 'speaker' | 'io';

export type TriggerSourceType =
  | 'event' | 'object' | 'system_event' | 'schedule' | 'incoming_webhook' | 'manual';

/** One entry of a trigger node's "fires on" list. */
export interface TriggerSource {
  trigger_type: TriggerSourceType;
  event_types?: string[];      // event / system_event
  classes?: string[];          // object
  min_confidence?: number;     // object
  camera_ids?: string[];
  cron?: string;               // schedule
}

export interface ConditionClause {
  field: string;               // score | camera_id | type | subtype | object_class | identity | custom
  op: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'not_in';
  value?: unknown;
  left?: string;               // {{template}} compared against value when field === 'custom'
}

/** Node config payload (React Flow node.data, stored verbatim on the server). */
export interface FlowNodeData extends Record<string, unknown> {
  label?: string;
  sources?: TriggerSource[];                       // trigger
  mode?: 'all' | 'any';                            // condition
  clauses?: ConditionClause[];                     // condition
  seconds?: number;                                // delay
  url?: string; method?: string; body?: Record<string, unknown>; // webhook
  headers?: Record<string, string>;
  title?: string; message?: string;                // push
  to?: string;                                     // email / sms
  camera_id?: string;                              // record / camera_* (empty = trigger camera)
  duration_s?: number;                             // record
  target_id?: string;                              // speaker / io
  params?: Record<string, unknown>;                // speaker / io extra params
}

export interface FlowGraphNode {
  id: string;
  type: FlowNodeType;
  position: { x: number; y: number };
  data: FlowNodeData;
}

export interface FlowGraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface FlowGraph {
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
}

export interface Flow {
  id: string;
  uuid: string;
  name: string;
  description: string | null;
  enabled: boolean;
  graph: FlowGraph;
  cooldown_s: number;
  incoming_token: string | null;
  last_run_ts: number | null;
  created_at: number | null;
}

export type FlowRunStatus = 'running' | 'success' | 'partial' | 'failed' | 'skipped';

export interface FlowNodeResult {
  node_id: string;
  type: FlowNodeType;
  status: 'success' | 'failed' | 'skipped';
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  started_ts: number | null;
  duration_ms: number | null;
}

export interface FlowRunSummary {
  id: string;
  flow_id: string;
  trigger_type: string;
  event_id: string | null;
  camera_id: string | null;
  status: FlowRunStatus;
  skip_reason: string | null;
  started_ts: number | null;
  finished_ts: number | null;
  duration_ms: number | null;
  created_at: number | null;
  node_statuses: Record<string, string>;
}

export interface FlowRunDetail extends Omit<FlowRunSummary, 'node_statuses'> {
  trigger_snapshot: Record<string, unknown> | null;
  node_results: FlowNodeResult[] | null;
}

export const ACTION_NODE_TYPES: FlowNodeType[] = [
  'webhook', 'push', 'email', 'sms', 'record', 'camera_enable', 'camera_disable', 'speaker', 'io'];

export const CONDITION_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in'] as const;
