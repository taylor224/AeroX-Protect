import { useMutation, useQuery } from '@tanstack/react-query';
import { Download, Loader2, RefreshCw, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useTranslation } from '@/i18n/TranslationProvider';
import { useFeatureFlag } from '@/lib/featureFlags';
import { formatDateTime } from '@/lib/format';
import { listCameras } from '@/pages/cameras/camera.api';
import { frameUrl } from '@/pages/playback/playback.api';
import { getClipModelStatus, installClipModel, semanticReindex, semanticSearch } from '@/pages/search/search.api';

export function SemanticSearchPage() {
  const intl = useIntl();
  const { locale } = useTranslation();
  const navigate = useNavigate();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('semantic_search');

  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameraMap = useMemo(
    () => new Map((camerasQuery.data?.items ?? []).map((c) => [String(c.id), c])),
    [camerasQuery.data],
  );

  const searchQuery = useQuery({
    queryKey: ['semantic', query],
    queryFn: () => semanticSearch(query),
    enabled: enabled && query.trim().length > 0,
  });

  const reindexMut = useMutation({
    mutationFn: () => semanticReindex(),
    onSuccess: (r) => toast.success(intl.formatMessage({ id: 'search.reindexed' }, { count: r.indexed })),
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const canSearch = hasPermission('ai', 'semantic_search');
  const canManage = hasPermission('settings', 'update');
  const [variant, setVariant] = useState<'cpu' | 'cuda'>('cpu');
  const modelQuery = useQuery({
    queryKey: ['clip-model'],
    queryFn: getClipModelStatus,
    enabled: enabled && canSearch,
    refetchInterval: (q) => {
      const p = q.state.data?.phase;
      return p === 'installing' || p === 'warming' ? 2000 : false;
    },
  });
  const model = modelQuery.data;
  const installMut = useMutation({
    mutationFn: (v: 'cpu' | 'cuda') => installClipModel(v),
    onSuccess: () => modelQuery.refetch(),
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  // phase transition → done: announce + reindex so the CLIP-space vectors exist
  const prevPhase = useRef<string | null>(null);
  useEffect(() => {
    const p = model?.phase;
    if (!p) return;
    if (prevPhase.current && prevPhase.current !== p) {
      if (p === 'done') {
        toast.success(intl.formatMessage({ id: 'search.model_done' }));
        reindexMut.mutate();
      } else if (p === 'error') {
        toast.error(intl.formatMessage({ id: 'search.model_error' }));
      }
    }
    prevPhase.current = p;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.phase]);

  if (!enabled) {
    return (
      <Card className="mx-auto mt-10 max-w-lg p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'search.disabled' })}
      </Card>
    );
  }

  const items = searchQuery.data?.items ?? [];
  const backend = searchQuery.data?.backend;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {intl.formatMessage({ id: 'menu.search' })}
        </h1>
        {hasPermission('ai', 'semantic_search') && (
          <Button variant="outline" size="sm" disabled={reindexMut.isPending} onClick={() => reindexMut.mutate()}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${reindexMut.isPending ? 'animate-spin' : ''}`} />
            {intl.formatMessage({ id: 'search.reindex' })}
          </Button>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(draft);
        }}
        className="flex items-center gap-2"
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={intl.formatMessage({ id: 'search.placeholder' })}
            className="pl-9"
          />
        </div>
        <Button type="submit">{intl.formatMessage({ id: 'search.go' })}</Button>
      </form>

      {model?.backend === 'clip' ? (
        <p className="text-xs text-emerald-500">{intl.formatMessage({ id: 'search.model_active' })}</p>
      ) : model || backend === 'hash' ? (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-52 flex-1 space-y-0.5">
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: 'search.model_title' })}
              </div>
              <p className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'search.hash_note' })}{' '}
                {model?.supported && intl.formatMessage({ id: 'search.model_desc' })}
              </p>
              {model && !model.supported && (
                <p className="text-xs text-muted-foreground">
                  {intl.formatMessage({ id: 'search.model_unsupported' })}
                </p>
              )}
            </div>
            {model?.supported && canManage && (model.phase === 'idle' || model.phase === 'error') && (
              <div className="flex items-center gap-2">
                <select
                  value={variant}
                  onChange={(e) => setVariant(e.target.value as 'cpu' | 'cuda')}
                  className="h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground"
                >
                  <option value="cpu">{intl.formatMessage({ id: 'search.model_variant_cpu' })}</option>
                  <option value="cuda">{intl.formatMessage({ id: 'search.model_variant_cuda' })}</option>
                </select>
                <Button size="sm" disabled={installMut.isPending} onClick={() => installMut.mutate(variant)}>
                  <Download className="mr-1.5 h-4 w-4" />
                  {intl.formatMessage({ id: 'search.model_install' })}
                </Button>
              </div>
            )}
          </div>
          {model && (model.phase === 'installing' || model.phase === 'warming') && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {intl.formatMessage({ id: `search.model_phase_${model.phase}` })}
              </div>
              {model.log.length > 0 && (
                <pre className="max-h-28 overflow-auto rounded bg-black/30 p-2 text-[10px] leading-4 text-muted-foreground">
                  {model.log.slice(-10).join('\n')}
                </pre>
              )}
            </div>
          )}
          {model?.phase === 'error' && (
            <pre className="max-h-28 overflow-auto rounded bg-red-500/10 p-2 text-[10px] leading-4 text-red-400">
              {[model.error ?? '', ...model.log.slice(-6)].join('\n')}
            </pre>
          )}
        </Card>
      ) : null}

      {searchQuery.isLoading ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {intl.formatMessage({ id: 'common.loading' })}
        </Card>
      ) : query && items.length === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {intl.formatMessage({ id: 'search.no_results' })}
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((it) => {
            const cam = cameraMap.get(it.camera_id);
            return (
              <button
                key={`${it.source_type}-${it.source_ref}`}
                onClick={() => cam && navigate(`/events?camera=${cam.uuid}`)}
                className="overflow-hidden rounded-xl border border-border text-left transition hover:border-primary"
              >
                <div className="relative aspect-video bg-black">
                  {cam && (
                    <img
                      src={frameUrl(cam.uuid, it.ts)}
                      alt={it.text ?? ''}
                      loading="lazy"
                      className="h-full w-full object-cover"
                      onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
                    />
                  )}
                  <span className="absolute right-1.5 top-1.5 rounded bg-primary/80 px-1.5 py-0.5 text-[11px] text-white">
                    {Math.round(it.score * 100)}%
                  </span>
                </div>
                <div className="space-y-0.5 px-2 py-1.5">
                  <div className="truncate text-xs font-medium text-foreground">{it.text}</div>
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="truncate">{cam?.name ?? it.camera_id}</span>
                    <span>{formatDateTime(it.ts, locale)}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
