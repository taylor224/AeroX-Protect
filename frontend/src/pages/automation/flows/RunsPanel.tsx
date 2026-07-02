// Run-history panel: run list → per-node trail; the selected run is replayed on the canvas.
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft } from 'lucide-react';
import { useIntl } from 'react-intl';

import { formatDateTime } from '@/lib/format';
import { listFlowRuns } from '@/pages/automation/flows/flow.api';
import { NODE_META } from '@/pages/automation/flows/flowCatalog';
import type { FlowNodeResult, FlowRunDetail, FlowRunSummary } from '@/types/flow';

const STATUS_DOT: Record<string, string> = {
  success: 'bg-emerald-500', partial: 'bg-amber-500', failed: 'bg-red-500',
  skipped: 'bg-slate-400', running: 'bg-sky-500 animate-pulse',
};

interface Props {
  flowUuid: string;
  selectedRunId: string | null;
  runDetail: FlowRunDetail | undefined;
  selectedNodeId: string | null;
  onSelectRun: (id: string | null) => void;
  onSelectNode: (id: string | null) => void;
}

export function RunsPanel({ flowUuid, selectedRunId, runDetail, selectedNodeId, onSelectRun, onSelectNode }: Props) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const runsQuery = useQuery({
    queryKey: ['flow-runs', flowUuid],
    queryFn: () => listFlowRuns(flowUuid),
    refetchInterval: 5000,
  });
  const runs = runsQuery.data?.items ?? [];

  if (selectedRunId && runDetail) {
    const results = runDetail.node_results ?? [];
    const selected = results.find((r) => r.node_id === selectedNodeId);
    return (
      <div className="flex h-full flex-col overflow-y-auto p-4">
        <button onClick={() => { onSelectRun(null); onSelectNode(null); }}
          className="mb-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-3.5 w-3.5" />{fm('flow.runs.back')}
        </button>
        <RunHeader run={runDetail} />
        {selected ? (
          <NodeResultDetail result={selected} />
        ) : (
          <div className="mt-3 space-y-1.5">
            {results.map((r) => (
              <button key={r.node_id} onClick={() => onSelectNode(r.node_id)}
                className="flex w-full items-center gap-2 rounded border border-border px-2.5 py-2 text-left hover:bg-secondary">
                <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[r.status] ?? 'bg-slate-400'}`} />
                <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                  {fm(`flow.node.${r.type}`)}
                  <span className="ml-1 text-muted-foreground">{r.node_id}</span>
                </span>
                <span className="text-[10px] text-muted-foreground">{r.duration_ms}ms</span>
              </button>
            ))}
            {!results.length && <p className="text-xs text-muted-foreground">{fm('flow.runs.noNodes')}</p>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <h3 className="mb-3 text-sm font-semibold text-foreground">{fm('flow.runs.title')}</h3>
      <div className="space-y-1.5">
        {runs.map((r: FlowRunSummary) => (
          <button key={r.id} onClick={() => onSelectRun(r.id)}
            className="flex w-full items-center gap-2 rounded border border-border px-2.5 py-2 text-left hover:bg-secondary">
            <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[r.status] ?? 'bg-slate-400'}`} />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-foreground">{formatDateTime(r.created_at)}</p>
              <p className="text-[10px] text-muted-foreground">
                {fm(`flow.source.${r.trigger_type}`)}
                {r.skip_reason ? ` · ${r.skip_reason}` : ''}
              </p>
            </div>
            <span className="text-[10px] text-muted-foreground">
              {r.duration_ms != null ? `${r.duration_ms}ms` : ''}
            </span>
          </button>
        ))}
        {!runs.length && !runsQuery.isLoading && (
          <p className="text-xs text-muted-foreground">{fm('flow.runs.empty')}</p>
        )}
      </div>
    </div>
  );
}

function RunHeader({ run }: { run: FlowRunDetail }) {
  const intl = useIntl();
  return (
    <div className="rounded border border-border p-2.5">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${STATUS_DOT[run.status] ?? 'bg-slate-400'}`} />
        <span className="text-xs font-medium text-foreground">
          {intl.formatMessage({ id: `flow.runstatus.${run.status}`, defaultMessage: run.status })}
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-muted-foreground">{formatDateTime(run.created_at)}</span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        {intl.formatMessage({ id: `flow.source.${run.trigger_type}`, defaultMessage: run.trigger_type })}
        {run.duration_ms != null ? ` · ${run.duration_ms}ms` : ''}
      </p>
    </div>
  );
}

function NodeResultDetail({ result }: { result: FlowNodeResult }) {
  const intl = useIntl();
  const fm = (id: string) => intl.formatMessage({ id });
  const Icon = NODE_META[result.type]?.icon;
  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-center gap-2">
        {Icon && (
          <span className={`flex h-6 w-6 items-center justify-center rounded ${NODE_META[result.type].chip}`}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        )}
        <div>
          <p className="text-xs font-medium text-foreground">{fm(`flow.node.${result.type}`)}</p>
          <p className="text-[10px] text-muted-foreground">
            {result.node_id} · {result.duration_ms}ms · {result.status}
          </p>
        </div>
      </div>
      {result.error && (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-[11px] text-red-700">{result.error}</div>
      )}
      <JsonBlock label={fm('flow.runs.input')} value={result.input} />
      <JsonBlock label={fm('flow.runs.output')} value={result.output} />
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null;
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-52 overflow-auto rounded bg-secondary p-2 text-[10px] leading-relaxed text-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
