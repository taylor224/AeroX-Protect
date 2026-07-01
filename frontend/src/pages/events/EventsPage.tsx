import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { useSearchParams } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useFeatureFlag } from '@/lib/featureFlags';
import { listCameras } from '@/pages/cameras/camera.api';
import { listBookmarks } from '@/pages/events/bookmark.api';
import { BookmarkButton } from '@/pages/events/components/BookmarkButton';
import { CameraPickGrid } from '@/pages/events/components/CameraPickGrid';
import { ManualRecordButton } from '@/pages/events/components/ManualRecordButton';
import { ProtectButton } from '@/pages/events/components/ProtectButton';
import { RetentionPolicyEditor } from '@/pages/events/components/RetentionPolicyEditor';
import { EventList } from '@/pages/events/components/EventList';
import { ShareLinkButton } from '@/pages/events/components/ShareLinkButton';
import { EventPolicyMatrix } from '@/pages/events/components/EventPolicyMatrix';
import { EventTimeline } from '@/pages/events/components/EventTimeline';
import { MotionOverlay } from '@/pages/events/components/MotionOverlay';
import { ScheduleEditor } from '@/pages/events/components/ScheduleEditor';
import { TimelapsePanel } from '@/pages/events/components/TimelapsePanel';
import { getEventOverlay, getEventTimeline, listEvents } from '@/pages/events/events.api';
import { eventColor } from '@/pages/events/eventMeta';
import { ExportPanel } from '@/pages/playback/components/ExportPanel';
import { Player } from '@/pages/playback/components/Player';
import { RecorderStatusBadge } from '@/pages/playback/components/RecorderStatusBadge';
import { getRecordingStatus, getSegments } from '@/pages/playback/playback.api';
import type { AxpEvent } from '@/types/p3';

const HOUR = 3600_000;
const PRESETS = [
  { key: '1h', ms: HOUR },
  { key: '6h', ms: 6 * HOUR },
  { key: '24h', ms: 24 * HOUR },
];
const FILTER_TYPES = ['motion', 'line_crossing', 'intrusion', 'tamper', 'object'];
type Tab = 'events' | 'schedule' | 'policies' | 'retention' | 'timelapse';

const pad = (n: number) => String(n).padStart(2, '0');
const toLocalInput = (ms: number) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const fromLocalInput = (s: string) => new Date(s).getTime();

export function EventsPage() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canSchedule = hasPermission('schedules', 'update');
  const canPolicy = hasPermission('policies', 'update');
  const canTimelapse = hasPermission('timelapse', 'create');
  const canControl = hasPermission('recordings', 'control');
  const canExport = hasPermission('clips', 'export');
  const bookmarksEnabled = useFeatureFlag('bookmarks');
  const canBookmark = hasPermission('bookmarks', 'update');
  const shareEnabled = useFeatureFlag('share_links');
  const canShare = hasPermission('share', 'create');

  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>('events');
  const [cameraUuid, setCameraUuid] = useState(searchParams.get('camera') ?? '');
  const [from, setFrom] = useState(() => Date.now() - 6 * HOUR);
  const [to, setTo] = useState(() => Date.now());
  const [types, setTypes] = useState<string[]>([]);
  const [onlyClips, setOnlyClips] = useState(false);
  const [selected, setSelected] = useState<AxpEvent | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);

  const applyPreset = (ms: number) => {
    setFrom(Date.now() - ms);
    setTo(Date.now());
  };

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];

  // No camera selected → entry is the camera grid (no auto-select to the first camera).
  const selectedUuid = cameraUuid;
  const selectedCamera = cameras.find((c) => c.uuid === selectedUuid);
  const cameraId = selectedCamera?.id;

  const pickCamera = (uuid: string) => {
    setCameraUuid(uuid);
    setSelected(null);
    setPlayhead(null);
    setTab('events');
    setSearchParams({ camera: uuid }, { replace: true });
  };
  const backToList = () => {
    setCameraUuid('');
    setSelected(null);
    setPlayhead(null);
    setSearchParams({}, { replace: true });
  };

  const eventsQuery = useQuery({
    queryKey: ['events', cameraId, from, to, types, onlyClips],
    queryFn: () =>
      listEvents({
        cameraId,
        types: types.length ? types : undefined,
        start: from,
        end: to,
        hasRecording: onlyClips ? true : undefined,
      }),
    enabled: !!cameraId && tab === 'events',
  });

  const timelineQuery = useQuery({
    queryKey: ['event-timeline', selectedUuid, from, to, types],
    queryFn: () => getEventTimeline(selectedUuid, from, to, types.length ? types : undefined),
    enabled: !!selectedUuid && tab === 'events',
  });

  const overlayQuery = useQuery({
    queryKey: ['overlay', selected?.id],
    queryFn: () => getEventOverlay(selected!.id),
    enabled: !!selected,
  });

  // Load recorded segments for the whole visible timeline range — not just a selected event's
  // clip window — so clicking anywhere on the timeline (seek) plays, and scrubbing across
  // events works. Previously this was gated on a selected event, so a bare timeline click had
  // no segments loaded and the player stayed blank.
  const segmentsQuery = useQuery({
    queryKey: ['event-segments', selectedUuid, from, to],
    queryFn: () => getSegments(selectedUuid, from, to),
    enabled: !!selectedUuid && tab === 'events',
  });

  // recording controls (merged from the former Playback page)
  const statusQuery = useQuery({
    queryKey: ['rec-status', selectedUuid],
    queryFn: () => getRecordingStatus(selectedUuid),
    enabled: !!selectedUuid,
    refetchInterval: 5000,
  });
  const status = statusQuery.data;
  const invalidateStatus = () => queryClient.invalidateQueries({ queryKey: ['rec-status', selectedUuid] });

  const bookmarksQuery = useQuery({
    queryKey: ['bookmarks', selectedUuid, from, to],
    queryFn: () => listBookmarks(selectedUuid, from, to),
    enabled: bookmarksEnabled && !!selectedUuid && tab === 'events',
  });

  const events = useMemo(() => eventsQuery.data?.items ?? [], [eventsQuery.data]);
  const segments = useMemo(() => segmentsQuery.data ?? [], [segmentsQuery.data]);
  const bookmarks = useMemo(() => bookmarksQuery.data ?? [], [bookmarksQuery.data]);

  const selectEvent = (ev: AxpEvent) => {
    setSelected(ev);
    setPlayhead(ev.start_ts);
  };
  const pickById = (eventId: string, ts: number) => {
    const ev = events.find((e) => e.id === eventId);
    if (ev) selectEvent(ev);
    else setPlayhead(ts);
  };

  // Clicking the timeline track scrubs to the exact clicked time on the continuous recording.
  // (Jumping to a specific event is done by clicking the event marker/list, which calls
  // pickById/selectEvent — the track itself must not hijack a plain seek.)
  const seekTo = (ts: number) => setPlayhead(ts);

  const toggleType = (t: string) =>
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const tabs: { key: Tab; show: boolean }[] = [
    { key: 'events', show: true },
    { key: 'schedule', show: hasPermission('schedules', 'read') },
    { key: 'policies', show: hasPermission('policies', 'read') },
    { key: 'retention', show: hasPermission('storage', 'read') },
    { key: 'timelapse', show: hasPermission('timelapse', 'read') },
  ];

  // ── entry: camera grid ──────────────────────────────────────────────────────
  if (!selectedUuid) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {intl.formatMessage({ id: 'menu.events' })}
        </h1>
        <CameraPickGrid cameras={cameras} onPick={pickCamera} />
      </div>
    );
  }

  // ── detail: one camera (events + recordings merged) ─────────────────────────
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={backToList} className="-ml-2">
          <ArrowLeft className="mr-1 h-4 w-4" />
          {intl.formatMessage({ id: 'event.back' })}
        </Button>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {selectedCamera?.name ?? ''}
        </h1>
        {status && <RecorderStatusBadge health={status.health} />}
        <div className="flex-1" />
        <div className="flex items-center gap-1 rounded border border-border p-0.5">
          {tabs
            .filter((t) => t.show)
            .map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  tab === t.key ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'
                }`}
              >
                {intl.formatMessage({ id: `event.tab.${t.key}` })}
              </button>
            ))}
        </div>
      </div>

      {tab === 'events' ? (
        <>
          {/* time range — direct date/time + quick presets */}
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="datetime-local"
              value={toLocalInput(from)}
              max={toLocalInput(to)}
              onChange={(e) => e.target.value && setFrom(fromLocalInput(e.target.value))}
              className="h-9 w-auto"
            />
            <span className="text-sm text-muted-foreground">→</span>
            <Input
              type="datetime-local"
              value={toLocalInput(to)}
              min={toLocalInput(from)}
              onChange={(e) => e.target.value && setTo(fromLocalInput(e.target.value))}
              className="h-9 w-auto"
            />
            <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
              {PRESETS.map((z) => (
                <button
                  key={z.key}
                  onClick={() => applyPreset(z.ms)}
                  className="rounded px-2.5 py-1 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  {intl.formatMessage({ id: 'event.recent' }, { d: z.key })}
                </button>
              ))}
            </div>
          </div>

          {/* type filters (clear button styling) + actions */}
          <div className="flex flex-wrap items-center gap-2">
            {FILTER_TYPES.map((t) => {
              const on = types.includes(t);
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium shadow-sm transition ${
                    on ? 'border-transparent text-white' : 'border-border bg-background text-foreground hover:bg-secondary'
                  }`}
                  style={on ? { background: eventColor(t) } : undefined}
                >
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: on ? 'rgba(255,255,255,0.9)' : eventColor(t) }}
                  />
                  {intl.formatMessage({ id: `event.type.${t}`, defaultMessage: t })}
                </button>
              );
            })}
            <button
              onClick={() => setOnlyClips((v) => !v)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium shadow-sm transition ${
                onlyClips ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-background text-foreground hover:bg-secondary'
              }`}
            >
              {intl.formatMessage({ id: 'event.only_clips' })}
            </button>

            <div className="flex-1" />

            {bookmarksEnabled && canBookmark && (
              <BookmarkButton
                cameraUuid={selectedUuid}
                atTs={playhead ?? from}
                recordingId={selected?.recording_id ?? null}
                eventId={selected ? String(selected.id) : null}
                eventLabel={selected ? intl.formatMessage({ id: `event.type.${selected.type}`, defaultMessage: selected.type }) : null}
              />
            )}
            {shareEnabled && canShare && selected && <ShareLinkButton eventId={String(selected.id)} />}
            {canControl && selected?.recording_id && (
              <ProtectButton key={selected.recording_id} recordingId={String(selected.recording_id)} />
            )}
            {status && (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
                <span className={`h-2 w-2 rounded-full ${status.health?.state === 'recording' ? 'bg-emerald-500' : 'bg-zinc-400'}`} />
                {intl.formatMessage({ id: 'recording.schedule_driven' })}
              </span>
            )}
            {canControl && status && (
              <ManualRecordButton cameraUuid={selectedUuid} active={status.active_manual} onChanged={invalidateStatus} />
            )}
            {canExport && <ExportPanel cameraUuid={selectedUuid} cameraId={cameraId} from={from} to={to} />}
          </div>

          {/* video + timeline — full width, larger */}
          <div className="space-y-3">
            <div className="relative">
              <Player
                cameraUuid={selectedUuid}
                from={from}
                to={to}
                segments={segments}
                seekTs={playhead}
                onTimeUpdate={setPlayhead}
              />
              {selected && overlayQuery.data && <MotionOverlay shapes={overlayQuery.data.shapes} />}
            </div>
            <Card className="bg-canvas p-3">
              <EventTimeline
                from={from}
                to={to}
                coverage={timelineQuery.data?.coverage ?? []}
                markers={timelineQuery.data?.markers ?? []}
                bookmarks={bookmarks}
                playhead={playhead ?? from}
                selectedId={selected?.id}
                onSeek={seekTo}
                onPickEvent={pickById}
              />
            </Card>
          </div>

          {/* event list — below, full width */}
          <Card className="overflow-hidden">
            <EventList events={events} selectedId={selected?.id ?? null} onSelect={selectEvent} />
          </Card>
        </>
      ) : tab === 'schedule' ? (
        <ScheduleEditor cameraUuid={selectedUuid} canEdit={canSchedule} />
      ) : tab === 'policies' ? (
        <EventPolicyMatrix cameraUuid={selectedUuid} cameraName={selectedCamera?.name ?? ''} canEdit={canPolicy} />
      ) : tab === 'retention' ? (
        <RetentionPolicyEditor cameraUuid={selectedUuid} canEdit={hasPermission('retention', 'manage')} />
      ) : (
        <TimelapsePanel cameraUuid={selectedUuid} canCreate={canTimelapse} />
      )}
    </div>
  );
}
