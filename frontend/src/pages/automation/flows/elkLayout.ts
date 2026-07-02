// elkjs auto-layout (left→right layered) for the flow editor canvas.
// elkjs is ~1.4MB minified — loaded on demand so it never weighs down the editor chunk.
import type { Edge, Node } from '@xyflow/react';

const OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.layered.spacing.nodeNodeBetweenLayers': '90',
  'elk.spacing.nodeNode': '40',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
};

export async function elkLayout<N extends Node>(nodes: N[], edges: Edge[]): Promise<N[]> {
  if (!nodes.length) return nodes;
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js');
  const elk = new ELK();
  const graph = {
    id: 'root',
    layoutOptions: OPTIONS,
    children: nodes.map((n) => ({
      id: n.id,
      width: n.measured?.width ?? 208,
      height: n.measured?.height ?? 56,
    })),
    edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  const res = await elk.layout(graph);
  const pos = new Map((res.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]));
  return nodes.map((n) => (pos.has(n.id) ? { ...n, position: pos.get(n.id)! } : n));
}
