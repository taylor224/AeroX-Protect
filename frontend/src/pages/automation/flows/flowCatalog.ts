// Node palette metadata + fresh-node defaults for the flow editor.
import {
  ArrowLeftRight,
  Bell,
  Camera,
  CameraOff,
  CircleDot,
  Clock,
  GitBranch,
  Mail,
  MessageSquare,
  Video,
  Volume2,
  Webhook,
  Zap,
  type LucideIcon,
} from 'lucide-react';

import type { FlowNodeData, FlowNodeType } from '@/types/flow';

export interface NodeMeta {
  icon: LucideIcon;
  /** accent classes for the node header icon chip */
  chip: string;
  defaultData: () => FlowNodeData;
}

export const NODE_META: Record<FlowNodeType, NodeMeta> = {
  trigger: {
    icon: Zap, chip: 'bg-amber-100 text-amber-700',
    defaultData: () => ({ sources: [{ trigger_type: 'object', classes: ['person'], min_confidence: 60 }] }),
  },
  condition: {
    icon: GitBranch, chip: 'bg-violet-100 text-violet-700',
    defaultData: () => ({ mode: 'all', clauses: [{ field: 'score', op: 'gte', value: 50 }] }),
  },
  delay: { icon: Clock, chip: 'bg-slate-100 text-slate-600', defaultData: () => ({ seconds: 5 }) },
  webhook: { icon: Webhook, chip: 'bg-sky-100 text-sky-700', defaultData: () => ({ url: '', method: 'POST' }) },
  push: { icon: Bell, chip: 'bg-emerald-100 text-emerald-700', defaultData: () => ({ title: '', message: '' }) },
  email: { icon: Mail, chip: 'bg-sky-100 text-sky-700', defaultData: () => ({ to: '' }) },
  sms: { icon: MessageSquare, chip: 'bg-emerald-100 text-emerald-700', defaultData: () => ({ to: '' }) },
  record: { icon: Video, chip: 'bg-red-100 text-red-700', defaultData: () => ({ camera_id: '', duration_s: 60 }) },
  camera_enable: { icon: Camera, chip: 'bg-teal-100 text-teal-700', defaultData: () => ({ camera_id: '' }) },
  camera_disable: { icon: CameraOff, chip: 'bg-orange-100 text-orange-700', defaultData: () => ({ camera_id: '' }) },
  speaker: { icon: Volume2, chip: 'bg-indigo-100 text-indigo-700', defaultData: () => ({ target_id: '', params: {} }) },
  io: { icon: ArrowLeftRight, chip: 'bg-indigo-100 text-indigo-700', defaultData: () => ({ target_id: '', params: {} }) },
};

/** Palette layout: section id → node types (labels via flow.node.* / flow.group.* i18n). */
export const PALETTE_GROUPS: { id: string; types: FlowNodeType[] }[] = [
  { id: 'start', types: ['trigger'] },
  { id: 'logic', types: ['condition', 'delay'] },
  { id: 'notify', types: ['push', 'email', 'sms', 'webhook'] },
  { id: 'device', types: ['record', 'camera_enable', 'camera_disable', 'speaker', 'io'] },
];

export const RUN_STATUS_RING: Record<string, string> = {
  success: 'ring-2 ring-emerald-500 border-emerald-500',
  failed: 'ring-2 ring-red-500 border-red-500',
  skipped: 'ring-2 ring-amber-400 border-amber-400',
};

export { CircleDot };

let seq = 0;
export function newNodeId(type: FlowNodeType): string {
  seq += 1;
  return `${type}_${Date.now().toString(36)}${seq}`;
}
