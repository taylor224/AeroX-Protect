// n8n-style visual flow editor: node palette → canvas (React Flow) → config panel.
// A second mode replays a selected run's per-node statuses on the same canvas.
import {
  addEdge,
  Background,
  ConnectionLineType,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type OnSelectionChangeParams,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, History, LayoutGrid, Play, Save } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { env } from '@/config/env';
import { createFlow, getFlow, getFlowRun, runFlow, updateFlow } from '@/pages/automation/flows/flow.api';
import { elkLayout } from '@/pages/automation/flows/elkLayout';
import { NODE_META, PALETTE_GROUPS, newNodeId } from '@/pages/automation/flows/flowCatalog';
import { flowNodeTypes, type EditorNode } from '@/pages/automation/flows/flowNodes';
import { NodeConfigPanel } from '@/pages/automation/flows/NodeConfigPanel';
import { RunsPanel } from '@/pages/automation/flows/RunsPanel';
import { listTargets } from '@/pages/automation/automation.api';
import { listCameras } from '@/pages/cameras/camera.api';
import type { Flow, FlowGraph, FlowNodeData, FlowNodeType } from '@/types/flow';

const EDGE_COLOR: Record<string, string> = {
  ok: '#059669', true: '#059669', err: '#dc2626', false: '#dc2626', out: '#f59e0b',
};

function styleEdge(e: Edge): Edge {
  const color = EDGE_COLOR[e.sourceHandle ?? ''] ?? 'var(--axp-border-strong, #94a3b8)';
  return {
    ...e,
    type: 'smoothstep',
    style: { stroke: color, strokeWidth: 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color },
  };
}

/** Strip editor-only fields + empty KV keys before persisting the canvas. */
function toGraph(nodes: EditorNode[], edges: Edge[]): FlowGraph {
  const cleanKv = (obj: unknown) =>
    obj && typeof obj === 'object'
      ? Object.fromEntries(Object.entries(obj as Record<string, unknown>).filter(([k]) => k !== ''))
      : undefined;
  return {
    nodes: nodes.map((n) => {
      const { runStatus: _rs, runDurationMs: _rd, runError: _re, runMode: _rm, ...data } = n.data;
      for (const k of ['headers', 'body', 'params'] as const) {
        if (data[k] !== undefined) data[k] = cleanKv(data[k]) as never;
      }
      return { id: n.id, type: n.type as FlowNodeType, position: n.position, data };
    }),
    edges: edges.map((e) => ({
      id: e.id, source: e.source, target: e.target,
      sourceHandle: e.sourceHandle ?? null, targetHandle: e.targetHandle ?? null,
    })),
  };
}

function freshTrigger(): EditorNode {
  return {
    id: newNodeId('trigger'), type: 'trigger', position: { x: 80, y: 160 },
    data: NODE_META.trigger.defaultData(),
  };
}

export function FlowEditorPage() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  );
}

function Editor() {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { flowUuid } = useParams();
  const isNew = !flowUuid;
  const { screenToFlowPosition, fitView } = useReactFlow();
  const wrapRef = useRef<HTMLDivElement>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<EditorNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [name, setName] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [cooldown, setCooldown] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [mode, setMode] = useState<'edit' | 'runs'>('edit');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const loadedRef = useRef(false);

  const flowQuery = useQuery({
    queryKey: ['flow', flowUuid],
    queryFn: () => getFlow(flowUuid!),
    enabled: !isNew,
  });
  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const targetsQuery = useQuery({ queryKey: ['action-targets'], queryFn: () => listTargets() });
  const runDetailQuery = useQuery({
    queryKey: ['flow-run', flowUuid, selectedRunId],
    queryFn: () => getFlowRun(flowUuid!, selectedRunId!),
    enabled: !isNew && !!selectedRunId,
  });

  // hydrate canvas once from the server graph (a new flow starts with a lone trigger node)
  useEffect(() => {
    if (loadedRef.current) return;
    if (isNew) {
      loadedRef.current = true;
      setNodes([freshTrigger()]);
      return;
    }
    const flow = flowQuery.data;
    if (!flow) return;
    loadedRef.current = true;
    setName(flow.name);
    setEnabled(flow.enabled);
    setCooldown(flow.cooldown_s ?? 0);
    setNodes((flow.graph?.nodes ?? []).map((n) => ({ ...n, data: { ...n.data } })) as EditorNode[]);
    setEdges((flow.graph?.edges ?? []).map((e) => styleEdge(e as Edge)));
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  }, [isNew, flowQuery.data, setNodes, setEdges, fitView]);

  // run replay: project the selected run's node statuses onto the canvas
  const runDetail = runDetailQuery.data;
  const displayNodes = useMemo(() => {
    if (mode !== 'runs') return nodes;
    const byNode = new Map((runDetail?.node_results ?? []).map((r) => [r.node_id, r]));
    return nodes.map((n) => {
      const r = byNode.get(n.id);
      return {
        ...n,
        data: {
          ...n.data, runMode: !!selectedRunId,
          runStatus: r?.status, runDurationMs: r?.duration_ms, runError: r?.error,
        },
      };
    });
  }, [nodes, mode, selectedRunId, runDetail]);

  const onConnect = useCallback((c: Connection) => {
    if (c.source === c.target) return;
    setEdges((es) => addEdge(styleEdge({ ...c, id: `e_${c.source}_${c.sourceHandle ?? 'out'}_${c.target}` } as Edge), es));
  }, [setEdges]);

  const onSelectionChange = useCallback(({ nodes: sel }: OnSelectionChangeParams) => {
    setSelectedNodeId(sel.length === 1 ? sel[0].id : null);
  }, []);

  const addNode = (type: FlowNodeType) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    const center = rect
      ? screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 3 })
      : { x: 200, y: 200 };
    const jitter = () => Math.round((Math.random() - 0.5) * 80);
    const node: EditorNode = {
      id: newNodeId(type), type,
      position: { x: center.x + jitter(), y: center.y + jitter() },
      data: NODE_META[type].defaultData(),
      selected: true,
    };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node]);
    setSelectedNodeId(node.id);
  };

  const patchNode = (id: string, patch: Partial<FlowNodeData>) =>
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));

  const deleteNode = (id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelectedNodeId(null);
  };

  const saveMut = useMutation({
    mutationFn: async () => {
      const body: Partial<Flow> = {
        name: name.trim(), enabled, cooldown_s: cooldown, graph: toGraph(nodes, edges),
      };
      return isNew ? createFlow(body) : updateFlow(flowUuid!, body);
    },
    onSuccess: (flow) => {
      queryClient.invalidateQueries({ queryKey: ['flows'] });
      queryClient.invalidateQueries({ queryKey: ['flow', flow.uuid] });
      toast.success(fm('flow.saved'));
      if (isNew) navigate(`/rules/flows/${flow.uuid}`, { replace: true });
    },
    onError: (e: { response?: { data?: { message?: string } } }) =>
      toast.error(e.response?.data?.message ?? fm('flow.saveFailed')),
  });

  const testMut = useMutation({
    mutationFn: async () => {
      // persist the canvas first so the test runs exactly what's on screen
      const body: Partial<Flow> = {
        name: name.trim() || fm('flow.untitled'), enabled, cooldown_s: cooldown, graph: toGraph(nodes, edges),
      };
      const flow = isNew ? await createFlow(body) : await updateFlow(flowUuid!, body);
      const run = await runFlow(flow.uuid);
      return { flow, run };
    },
    onSuccess: ({ flow, run }) => {
      queryClient.invalidateQueries({ queryKey: ['flows'] });
      queryClient.invalidateQueries({ queryKey: ['flow-runs', flow.uuid] });
      toast.success(fm(`flow.runstatus.${run.status}`));
      if (isNew) {
        navigate(`/rules/flows/${flow.uuid}`, { replace: true });
        return;                              // route remount picks the run up from the list
      }
      setMode('runs');
      setSelectedRunId(run.id);
      setSelectedNodeId(null);
    },
    onError: (e: { response?: { data?: { message?: string } } }) =>
      toast.error(e.response?.data?.message ?? fm('flow.saveFailed')),
  });

  const autoLayout = async () => {
    const laid = await elkLayout(nodes, edges);
    setNodes(laid);
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  };

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;
  const incomingUrl = flowQuery.data?.incoming_token
    ? `${window.location.origin}${env.apiUrl}/automation/flows/incoming/${flowQuery.data.incoming_token}`
    : fm('flow.hookAfterSave');

  return (
    <div className="flex h-[calc(100vh-7.5rem)] min-h-[480px] flex-col gap-3">
      {/* top bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="icon" onClick={() => navigate('/rules?tab=flows')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <Input value={name} onChange={(e) => setName(e.target.value)}
          placeholder={fm('flow.namePh')} className="w-56" />
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {fm('flow.field.cooldown')}
          <Input type="number" min={0} max={3600} value={cooldown} className="w-20"
            onChange={(e) => setCooldown(Number(e.target.value))} />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {fm('flow.field.enabled')}
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </label>
        <div className="flex-1" />
        <Button variant="outline" size="sm" onClick={autoLayout}>
          <LayoutGrid className="mr-1 h-3.5 w-3.5" />{fm('flow.autoLayout')}
        </Button>
        <Button variant="outline" size="sm"
          onClick={() => { setMode(mode === 'edit' ? 'runs' : 'edit'); setSelectedRunId(null); setSelectedNodeId(null); }}>
          <History className="mr-1 h-3.5 w-3.5" />
          {fm(mode === 'edit' ? 'flow.showRuns' : 'flow.backToEdit')}
        </Button>
        <Button variant="outline" size="sm" disabled={testMut.isPending} onClick={() => testMut.mutate()}>
          <Play className="mr-1 h-3.5 w-3.5" />{fm('flow.test')}
        </Button>
        <Button size="sm" disabled={!name.trim() || saveMut.isPending} onClick={() => saveMut.mutate()}>
          <Save className="mr-1 h-3.5 w-3.5" />{fm('common.save')}
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 gap-3">
        {/* palette */}
        {mode === 'edit' && (
          <div className="w-44 shrink-0 space-y-3 overflow-y-auto rounded border border-border bg-white p-3">
            {PALETTE_GROUPS.map((g) => (
              <div key={g.id}>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {fm(`flow.group.${g.id}`)}
                </p>
                <div className="space-y-1">
                  {g.types.map((t) => {
                    const Icon = NODE_META[t].icon;
                    return (
                      <button key={t} onClick={() => addNode(t)}
                        className="flex w-full items-center gap-2 rounded border border-border px-2 py-1.5 text-left text-xs text-foreground hover:border-primary hover:bg-primary/5">
                        <span className={`flex h-5 w-5 items-center justify-center rounded ${NODE_META[t].chip}`}>
                          <Icon className="h-3 w-3" />
                        </span>
                        {fm(`flow.node.${t}`)}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* canvas */}
        <div ref={wrapRef} className="min-w-0 flex-1 overflow-hidden rounded border border-border bg-white">
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={flowNodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            connectionLineType={ConnectionLineType.SmoothStep}
            deleteKeyCode={mode === 'edit' ? ['Backspace', 'Delete'] : null}
            nodesDraggable={mode === 'edit'}
            nodesConnectable={mode === 'edit'}
            elementsSelectable
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        {/* right panel */}
        <div className="w-80 shrink-0 overflow-hidden rounded border border-border bg-white">
          {mode === 'runs' && flowUuid ? (
            <RunsPanel
              flowUuid={flowUuid}
              selectedRunId={selectedRunId}
              runDetail={runDetail}
              selectedNodeId={selectedNodeId}
              onSelectRun={setSelectedRunId}
              onSelectNode={setSelectedNodeId}
            />
          ) : selectedNode ? (
            <NodeConfigPanel
              key={selectedNode.id}
              node={selectedNode}
              nodes={nodes}
              edges={edges}
              cameras={camerasQuery.data?.items ?? []}
              targets={targetsQuery.data ?? []}
              incomingUrl={incomingUrl}
              onChange={(patch) => patchNode(selectedNode.id, patch)}
              onDelete={() => deleteNode(selectedNode.id)}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-6 text-center text-xs text-muted-foreground">
              {fm(mode === 'runs' ? 'flow.runs.selectHint' : 'flow.selectNodeHint')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
