import { useQuery } from '@tanstack/react-query';
import { Maximize, Minimize, Pause, Play, Tags, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { CameraThumbnail } from '@/components/CameraThumbnail';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { listCameras } from '@/pages/cameras/camera.api';
import {
  createDashboard,
  deleteDashboard,
  getDashboard,
  listDashboards,
  saveDashboard,
} from '@/pages/dashboards/dashboard.api';
import { listEvents } from '@/pages/events/events.api';
import { CameraTile } from '@/pages/live/components/CameraTile';
import { LiveGrid } from '@/pages/live/components/LiveGrid';
import { LAYOUT_PRESETS, presetLayout } from '@/pages/live/layouts';
import type { DashboardLayout, RatioMode } from '@/types/axp';

const SPOTLIGHT_WINDOW_MS = 20_000;
const DWELLS = [5, 10, 30];
const RATIO_MODES: RatioMode[] = ['fit', 'crop', 'stretch'];

export function LivePage() {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const canEdit = hasPermission('dashboards', 'update') || hasPermission('dashboards', 'create');

  const [layout, setLayout] = useState<DashboardLayout>(() => presetLayout('4'));
  const [selectedDash, setSelectedDash] = useState<string>('');
  const [name, setName] = useState('');
  const [editMode, setEditMode] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [pickerCell, setPickerCell] = useState<string | null>(null);
  const [enlargedUuid, setEnlargedUuid] = useState<string | null>(null); // double-click → big view
  const [audioOn, setAudioOn] = useState<Set<string>>(new Set()); // session-only "listen" set
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [activePage, setActivePage] = useState(0);

  const rootRef = useRef<HTMLDivElement>(null);

  // ── page model: legacy single-page = layout itself; multi-page = layout.pages[] ──
  const isMulti = Array.isArray(layout.pages);
  const pages: DashboardLayout[] = isMulti ? (layout.pages as DashboardLayout[]) : [layout];
  const pageIdx = Math.min(activePage, pages.length - 1);
  const page = pages[pageIdx] ?? pages[0];
  const seq = layout.sequence ?? { enabled: false, dwell_s: 10 };
  const showNames = !!page.show_names;

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const dashboardsQuery = useQuery({ queryKey: ['dashboards'], queryFn: listDashboards });

  const cameras = camerasQuery.data?.items ?? [];
  const cameraMap = useMemo(() => new Map(cameras.map((c) => [c.uuid, c])), [cameras]);
  const assignedUuids = useMemo(
    () => new Set((page.cells ?? []).map((c) => c.camera_uuid).filter(Boolean) as string[]),
    [page],
  );

  // edit the ACTIVE page and mark dirty (Save button surfaces — non-blocking)
  const editPage = useCallback((next: DashboardLayout | ((p: DashboardLayout) => DashboardLayout)) => {
    setLayout((cur) => {
      const curPages = Array.isArray(cur.pages) ? (cur.pages as DashboardLayout[]) : [cur];
      const idx = Math.min(activePage, curPages.length - 1);
      const updated = typeof next === 'function' ? (next as (p: DashboardLayout) => DashboardLayout)(curPages[idx]) : next;
      if (Array.isArray(cur.pages)) {
        return { ...cur, pages: curPages.map((p, i) => (i === idx ? updated : p)) };
      }
      return updated;
    });
    setDirty(true);
  }, [activePage]);

  // edit dashboard-level fields (sequence config, pages array)
  const editDashboard = useCallback((patch: Partial<DashboardLayout>) => {
    setLayout((cur) => ({ ...cur, ...patch }));
    setDirty(true);
  }, []);

  // L4 event spotlight (highlights a tile when its camera has a recent event)
  const spotlightQuery = useQuery({
    queryKey: ['live-spotlight'],
    queryFn: () => listEvents({ start: Date.now() - SPOTLIGHT_WINDOW_MS, end: Date.now() }),
    enabled: assignedUuids.size > 0,
    refetchInterval: 5000,
  });
  const spotlightUuids = useMemo(() => {
    const idToUuid = new Map(cameras.map((c) => [String(c.id), c.uuid]));
    const s = new Set<string>();
    for (const e of spotlightQuery.data?.items ?? []) {
      const u = idToUuid.get(String(e.camera_id));
      if (u && assignedUuids.has(u)) s.add(u);
    }
    return s;
  }, [cameras, spotlightQuery.data, assignedUuids]);

  const loadDashboard = useCallback(async (uuid: string) => {
    setSelectedDash(uuid);
    setEditMode(false);
    setDirty(false);
    setActivePage(0);
    if (!uuid) {
      setLayout(presetLayout('4'));
      setName('');
      return;
    }
    const d = await getDashboard(uuid);
    setLayout(d.layout?.pages || d.layout?.cells ? d.layout : presetLayout('4'));
    setName(d.name);
  }, []);

  useEffect(() => {
    const dashes = dashboardsQuery.data;
    if (dashes && dashes.length && !selectedDash) void loadDashboard(dashes[0].uuid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardsQuery.data]);

  // per-dashboard sequence: auto-rotate among this dashboard's pages (paused while editing)
  useEffect(() => {
    if (!seq.enabled || editMode || pages.length < 2) return;
    const t = setTimeout(() => {
      setActivePage((i) => (i + 1) % pages.length);
    }, Math.max(2, seq.dwell_s) * 1000);
    return () => clearTimeout(t);
  }, [seq.enabled, seq.dwell_s, editMode, pages.length, pageIdx]);

  // fullscreen (kiosk): real Fullscreen API + ESC to exit; sync state on fullscreenchange
  const enterFullscreen = () => {
    setFullscreen(true);
    rootRef.current?.requestFullscreen?.().catch(() => {});
  };
  const exitFullscreen = useCallback(() => {
    setFullscreen(false);
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    const onFsChange = () => {
      if (!document.fullscreenElement) setFullscreen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreen) exitFullscreen();
    };
    document.addEventListener('fullscreenchange', onFsChange);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange);
      window.removeEventListener('keydown', onKey);
    };
  }, [fullscreen, exitFullscreen]);

  const applyPreset = (key: string) => {
    const existing = (page.cells ?? []).map((c) => c.camera_uuid);
    const next = presetLayout(key, existing);
    editPage({ ...next, name: page.name, show_names: page.show_names, ratio_mode: page.ratio_mode ?? 'fit' });
  };

  const assignCamera = (cameraUuid: string) => {
    if (!pickerCell) return;
    editPage((l) => ({
      ...l,
      cells: (l.cells ?? []).map((c) => (c.i === pickerCell ? { ...c, camera_uuid: cameraUuid } : c)),
    }));
    setPickerCell(null);
  };

  const cycleRatio = () => {
    const next = RATIO_MODES[(RATIO_MODES.indexOf(page.ratio_mode ?? 'fit') + 1) % RATIO_MODES.length];
    editPage((l) => ({ ...l, ratio_mode: next }));
  };

  const toggleNames = () => editPage((l) => ({ ...l, show_names: !l.show_names }));

  // ── multi-page management ──────────────────────────────────────────────────
  const addPage = () => {
    const base = presetLayout('4');
    const newPage: DashboardLayout = { ...base, name: `Page ${pages.length + 1}` };
    const nextPages = [...pages.map((p, i) => (i === 0 && !isMulti ? { ...p, name: p.name ?? 'Page 1' } : p)), newPage];
    editDashboard({ pages: nextPages });
    setActivePage(nextPages.length - 1);
  };
  const removePage = (idx: number) => {
    if (pages.length <= 1) return;
    const nextPages = pages.filter((_, i) => i !== idx);
    editDashboard(nextPages.length === 1
      ? { ...nextPages[0], pages: undefined, sequence: layout.sequence }   // collapse back to single-page
      : { pages: nextPages });
    setActivePage((i) => Math.max(0, Math.min(i, nextPages.length - 1)));
  };
  const renamePage = (idx: number, value: string) => {
    if (!isMulti) { editDashboard({ pages: [{ ...page, name: value }] }); return; }
    editDashboard({ pages: pages.map((p, i) => (i === idx ? { ...p, name: value } : p)) });
  };
  const setSequence = (patch: Partial<{ enabled: boolean; dwell_s: number }>) =>
    editDashboard({ sequence: { ...seq, ...patch } });

  const toggleAudio = (uuid: string) =>
    setAudioOn((prev) => {
      const n = new Set(prev);
      n.has(uuid) ? n.delete(uuid) : n.add(uuid);
      return n;
    });

  const save = async () => {
    try {
      if (selectedDash) {
        await saveDashboard(selectedDash, { layout, name: name || undefined });
      } else {
        const created = await createDashboard(name || intl.formatMessage({ id: 'dashboard.untitled' }), layout);
        setSelectedDash(created.uuid);
        void dashboardsQuery.refetch();
      }
      toast.success(intl.formatMessage({ id: 'dashboard.saved' }));
      setEditMode(false);
      setDirty(false);
    } catch {
      toast.error(intl.formatMessage({ id: 'dashboard.save_failed' }));
    }
  };

  const removeDashboard = async () => {
    if (!selectedDash) return;
    try {
      await deleteDashboard(selectedDash);
      toast.success(intl.formatMessage({ id: 'dashboard.deleted' }));
      const rest = (dashboardsQuery.data ?? []).filter((d) => d.uuid !== selectedDash);
      await dashboardsQuery.refetch();
      setEditMode(false);
      await loadDashboard(rest[0]?.uuid ?? '');
    } catch {
      toast.error(intl.formatMessage({ id: 'common.error' }));
    }
  };

  const grid = (
    <LiveGrid
      layout={page}
      cameras={cameraMap}
      editMode={editMode}
      showNames={showNames}
      spotlightUuids={spotlightUuids}
      audioOn={audioOn}
      onToggleAudio={toggleAudio}
      onChange={editPage}
      onAssignCell={setPickerCell}
      onEnlarge={setEnlargedUuid}
    />
  );

  // page tabs: switch pages (view) / add·rename·delete + sequence config (edit)
  const pageBar = (isMulti || editMode) && (
    <div className="flex flex-wrap items-center gap-1.5">
      {pages.map((p, i) => (
        <div key={i}
          className={cn('flex items-center gap-1 rounded border px-2 py-1 text-xs',
            i === pageIdx ? 'border-primary text-primary' : 'border-border text-muted-foreground')}>
          {editMode && i === pageIdx ? (
            <input value={p.name ?? `Page ${i + 1}`} onChange={(e) => renamePage(i, e.target.value)}
              className="w-20 bg-transparent outline-none" />
          ) : (
            <button onClick={() => setActivePage(i)}>{p.name ?? `Page ${i + 1}`}</button>
          )}
          {editMode && pages.length > 1 && (
            <button onClick={() => removePage(i)} aria-label="remove page" className="text-muted-foreground hover:text-destructive">
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      ))}
      {editMode && (
        <Button variant="outline" size="sm" className="h-7" onClick={addPage}>
          + {intl.formatMessage({ id: 'live.add_page' })}
        </Button>
      )}
    </div>
  );

  const enlargedCamera = enlargedUuid ? cameraMap.get(enlargedUuid) : undefined;
  const enlargeOverlay = (
    <Dialog open={!!enlargedCamera} onOpenChange={(o) => !o && setEnlargedUuid(null)}>
      <DialogContent className="h-[94vh] w-[97vw] max-w-none border-0 bg-transparent p-0 shadow-none">
        {enlargedCamera && (
          <>
            <DialogHeader className="sr-only">
              <DialogTitle>{enlargedCamera.name}</DialogTitle>
            </DialogHeader>
            <div className="h-full w-full overflow-hidden rounded-lg bg-black">
              <CameraTile camera={enlargedCamera} ratioMode="fit" showName audioOn={audioOn.has(enlargedCamera.uuid)}
                onToggleAudio={() => toggleAudio(enlargedCamera.uuid)} />
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );

  // ── kiosk / fullscreen: just the wall, ESC to exit ─────────────────────────
  if (fullscreen) {
    return (
      <div ref={rootRef} className="fixed inset-0 z-[60] bg-canvas p-1">
        {grid}
        {enlargeOverlay}
        <button
          onClick={exitFullscreen}
          className="absolute right-3 top-3 rounded bg-black/50 p-1.5 text-white/50 opacity-0 transition-opacity hover:text-white focus:opacity-100"
          aria-label="exit fullscreen"
          title="ESC"
        >
          <Minimize className="h-4 w-4" />
        </button>
      </div>
    );
  }

  const iconBtn = (active: boolean) =>
    cn(
      'flex items-center gap-1 rounded px-2.5 py-1 text-sm transition-colors',
      active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
    );

  return (
    <div ref={rootRef} className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="h-9 rounded border border-input bg-background px-2 text-sm"
          value={selectedDash}
          onChange={(e) => void loadDashboard(e.target.value)}
        >
          <option value="">{intl.formatMessage({ id: 'dashboard.new' })}</option>
          {(dashboardsQuery.data ?? []).map((d) => (
            <option key={d.uuid} value={d.uuid}>{d.name}</option>
          ))}
        </select>

        {/* edit-only: layout presets */}
        {editMode && (
          <div className="flex items-center gap-1 rounded border border-border p-0.5">
            {LAYOUT_PRESETS.map((p) => (
              <button key={p.key} onClick={() => applyPreset(p.key)}
                className="rounded px-2.5 py-1 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
                {p.label}
              </button>
            ))}
          </div>
        )}

        {editMode && (
          <Button variant="outline" size="sm" onClick={cycleRatio}>
            {intl.formatMessage({ id: 'live.ratio' })}: {intl.formatMessage({ id: `live.ratio.${layout.ratio_mode ?? 'fit'}` })}
          </Button>
        )}

        {/* names toggle (view + edit) */}
        <button onClick={toggleNames} className={iconBtn(showNames)}>
          <Tags className="h-3.5 w-3.5" />
          {intl.formatMessage({ id: 'live.names' })}
        </button>

        {/* per-dashboard page auto-rotation (sequence) */}
        {pages.length >= 2 && (
          <div className="flex items-center gap-1 rounded border border-border p-0.5">
            <button onClick={() => setSequence({ enabled: !seq.enabled })} className={iconBtn(seq.enabled)}>
              {seq.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {intl.formatMessage({ id: 'live.sequence' })}
            </button>
            <select className="h-7 rounded border border-input bg-background px-1 text-xs"
              value={seq.dwell_s} onChange={(e) => setSequence({ dwell_s: Number(e.target.value) })}>
              {DWELLS.map((d) => <option key={d} value={d}>{d}s</option>)}
            </select>
          </div>
        )}

        <div className="flex-1" />

        {editMode && name !== undefined && (
          <Input className="h-9 w-40" placeholder={intl.formatMessage({ id: 'dashboard.name' })}
            value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} />
        )}

        {/* fullscreen / kiosk (hidden in edit) */}
        {!editMode && (
          <Button variant="outline" size="sm" onClick={enterFullscreen} title={intl.formatMessage({ id: 'live.fullscreen' })}>
            <Maximize className="h-4 w-4" />
          </Button>
        )}

        {canEdit && !editMode && (
          <Button variant="outline" size="sm" onClick={() => setEditMode(true)}>
            {intl.formatMessage({ id: 'live.edit' })}
          </Button>
        )}
        {canEdit && editMode && (
          <>
            {selectedDash && (
              <Button variant="ghost" size="icon" onClick={() => setConfirmDelete(true)}
                title={intl.formatMessage({ id: 'common.delete' })} aria-label="delete dashboard">
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => void loadDashboard(selectedDash)}>
              {intl.formatMessage({ id: 'common.cancel' })}
            </Button>
          </>
        )}
        {canEdit && (dirty || editMode) && (
          <Button size="sm" onClick={save}>{intl.formatMessage({ id: 'common.save' })}</Button>
        )}
      </div>

      {pageBar}

      <div className="min-h-0 flex-1 rounded-lg bg-canvas p-1">{grid}</div>

      {enlargeOverlay}

      {/* camera picker (edit-mode empty cell) */}
      <Dialog open={!!pickerCell} onOpenChange={(o) => !o && setPickerCell(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'live.pick_camera' })}</DialogTitle>
          </DialogHeader>
          <div className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-auto py-1 sm:grid-cols-3">
            {cameras.map((c) => (
              <button key={c.uuid} onClick={() => assignCamera(c.uuid)}
                className="overflow-hidden rounded-lg border border-border text-left transition hover:border-primary">
                <div className="relative aspect-video bg-black">
                  <CameraThumbnail cameraUuid={c.uuid} status={c.status} className="absolute inset-0 h-full w-full" iconClassName="h-7 w-7" />
                  {assignedUuids.has(c.uuid) && (
                    <span className="absolute right-1.5 top-1.5 rounded bg-primary/80 px-1.5 py-0.5 text-[10px] text-white">
                      {intl.formatMessage({ id: 'live.in_use' })}
                    </span>
                  )}
                  <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1.5 text-xs font-medium text-white">
                    {c.name}
                  </span>
                </div>
              </button>
            ))}
            {cameras.length === 0 && (
              <p className="col-span-full p-6 text-center text-sm text-muted-foreground">
                {intl.formatMessage({ id: 'camera.empty' })}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={intl.formatMessage({ id: 'dashboard.delete_title' })}
        description={intl.formatMessage({ id: 'dashboard.delete_desc' }, { name })}
        confirmLabel={intl.formatMessage({ id: 'common.delete' })}
        destructive
        onConfirm={removeDashboard}
      />
    </div>
  );
}
