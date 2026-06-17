import { useMutation, useQuery } from '@tanstack/react-query';
import { RefreshCw, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
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
import { semanticReindex, semanticSearch } from '@/pages/search/search.api';

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

      {backend === 'hash' && (
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'search.hash_note' })}</p>
      )}

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
