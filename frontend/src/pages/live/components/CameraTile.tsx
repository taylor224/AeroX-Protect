import { Gamepad2, Plus, Volume2, VolumeX, X } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { CameraThumbnail } from '@/components/CameraThumbnail';
import { useFeatureFlag } from '@/lib/featureFlags';
import { cn } from '@/lib/utils';
import { FisheyeViewer } from '@/pages/live/components/FisheyeViewer';
import { MaskOverlay } from '@/pages/live/components/MaskOverlay';
import { PtzControls } from '@/pages/live/components/PtzControls';
import { TalkButton } from '@/pages/live/components/TalkButton';
import { VideoPlayer } from '@/pages/live/components/VideoPlayer';
import { hevcMseSupported } from '@/pages/live/mseStream';
import type { Camera, RatioMode, Stream } from '@/types/axp';

const DOT: Record<string, string> = {
  online: 'bg-emerald-500',
  offline: 'bg-zinc-400',
  unauthorized: 'bg-red-500',
  error: 'bg-red-500',
  unknown: 'bg-zinc-300',
};

/** The HD (main/full) stream, if it is distinct from the default live stream. */
function hdStream(camera: Camera): Stream | undefined {
  const streams = (camera.streams ?? []).filter((s) => s.enabled !== false);
  const main = streams.find((s) => s.is_default_full) ?? streams.find((s) => s.role === 'main');
  if (!main?.go2rtc_name) return undefined;
  const live = streams.find((s) => s.is_default_live) ?? streams[0];
  return main.go2rtc_name === live?.go2rtc_name ? undefined : main;
}

/** True if this browser can actually play `stream` live. go2rtc only transcodes the
 *  default-live stream, so a non-default H.265 stream needs HEVC-capable MSE. */
function playableLive(stream: Stream): boolean {
  return stream.codec !== 'h265' || hevcMseSupported();
}

/** go2rtc stream to play live, or null when the camera has no usable stream (a streamless
 *  camera must show a placeholder — guessing a synthetic name just 404-spams /live/ws-ticket). */
function liveStreamName(camera: Camera, streamRole?: 'main' | 'sub'): string | null {
  if (streamRole === 'main') {
    const hd = hdStream(camera);
    if (hd && playableLive(hd)) return hd.go2rtc_name;
  }
  const s = camera.streams?.find((st) => st.is_default_live) ?? camera.streams?.[0];
  return s?.go2rtc_name ?? null;
}

export function CameraTile({
  camera,
  ratioMode = 'fit',
  editMode = false,
  active = true,
  spotlight = false,
  showName = false,
  audioOn = false,
  streamRole,
  enlarged = false,
  enlargedHost = null,
  onSetStreamRole,
  onToggleAudio,
  onRemove,
  onClickEmpty,
  onEnlarge,
}: {
  camera?: Camera;
  ratioMode?: RatioMode;
  editMode?: boolean;
  active?: boolean;
  spotlight?: boolean;
  showName?: boolean;
  audioOn?: boolean;
  /** per-cell stream quality: 'main' = HD, 'sub'/undefined = default live (SD) */
  streamRole?: 'main' | 'sub';
  /** enlarged: reparent the ALREADY-PLAYING media into `enlargedHost` (no reconnect) */
  enlarged?: boolean;
  enlargedHost?: HTMLElement | null;
  onSetStreamRole?: (role: 'main' | 'sub') => void;
  onToggleAudio?: () => void;
  onRemove?: () => void;
  onClickEmpty?: () => void;
  onEnlarge?: () => void;
}) {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const talkEnabled = useFeatureFlag('two_way_audio');
  const [showPtz, setShowPtz] = useState(false);

  // The tile's media/controls render into this detached div (via createPortal) so the SAME
  // DOM — including the playing <video> and its MSE/WebRTC session — can be moved between
  // the grid cell and the enlarge overlay. Enlarging must NOT remount the player: a remount
  // reconnects the stream and cold-starts (spinner for seconds); a reparented <video> keeps
  // its decoder and buffer and resumes instantly.
  const rootRef = useRef<HTMLDivElement | null>(null);
  const portalDiv = useMemo(() => {
    const d = document.createElement('div');
    d.className = 'h-full w-full';
    return d;
  }, []);
  const attachPortal = useCallback(
    (host: HTMLElement | null) => {
      if (!host || portalDiv.parentElement === host) return;
      host.appendChild(portalDiv);
      // some browsers pause a reparented <video>; resume the live stream in place
      const v = portalDiv.querySelector('video');
      if (v) void (v as HTMLVideoElement).play().catch(() => {});
    },
    [portalDiv],
  );
  useLayoutEffect(() => {
    attachPortal((enlarged && enlargedHost) || rootRef.current);
  }, [enlarged, enlargedHost, attachPortal]);
  // CALLBACK ref, not just the layout effect: the tile's first render often happens
  // before the cameras query resolves (camera=undefined → placeholder, no shell div).
  // The effect runs once against that render and its deps never change, so when the
  // real shell finally mounts nothing re-attached portalDiv — the player streamed
  // into a detached DOM and the tile stayed black. A callback ref fires on every
  // mount of the shell, so the portal is attached no matter the load order.
  const hostRef = useCallback(
    (el: HTMLDivElement | null) => {
      rootRef.current = el;
      if (el && !enlarged) attachPortal(el);
    },
    [enlarged, attachPortal],
  );
  useEffect(() => () => portalDiv.remove(), [portalDiv]);

  if (!camera) {
    return (
      <button
        onClick={onClickEmpty}
        disabled={!editMode}
        className={cn(
          'rgl-no-drag flex h-full w-full items-center justify-center rounded border border-dashed border-white/15 bg-white/[0.02] text-white/30',
          editMode && 'transition-colors hover:border-primary/50 hover:text-primary',
        )}
      >
        {editMode && <Plus className="h-6 w-6" />}
      </button>
    );
  }

  const canPtz = camera.ptz_supported && hasPermission('ptz', 'control');
  const canTalk = !!camera.two_way_audio && talkEnabled && hasPermission('audio', 'talk');
  const canListen = !!camera.audio_supported && !editMode;
  const streamName = liveStreamName(camera, streamRole);

  const content = (
    <div
      onDoubleClick={!editMode ? onEnlarge : undefined}
      className={cn(
        'group relative h-full w-full overflow-hidden rounded bg-black transition-shadow',
        // exempt the tile from react-grid-layout's drag-detection in view mode so its mousedown
        // handling can't swallow the first click of a double-click (drag is edit-mode only)
        !editMode && 'rgl-no-drag',
        !editMode && onEnlarge && (enlarged ? 'cursor-zoom-out' : 'cursor-zoom-in'),
      )}
    >
      {camera.fisheye ? (
        <FisheyeViewer camera={camera} active={active && !editMode} />
      ) : streamName ? (
        <VideoPlayer
          go2rtcName={streamName}
          ratioMode={ratioMode}
          active={active && !editMode}
          muted={!audioOn}
        />
      ) : (
        // no usable stream (e.g. wiped by a bad edit while the camera was offline) —
        // show the cached thumbnail/offline mark instead of dialing a nonexistent stream
        <CameraThumbnail cameraUuid={camera.uuid} status={camera.status} className="h-full w-full" />
      )}

      {!editMode && <MaskOverlay cameraUuid={camera.uuid} />}

      {/* name label — always shown when showName, else on hover only */}
      <div
        className={cn(
          'pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between bg-gradient-to-b from-black/55 to-transparent p-2 transition-opacity',
          showName ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
        )}
      >
        <span className="flex items-center gap-1.5 text-xs font-medium text-white drop-shadow">
          <span className={cn('h-1.5 w-1.5 rounded-full', DOT[camera.status])} />
          {camera.name}
        </span>
      </div>

      {editMode && (
        <button
          onClick={onRemove}
          className="rgl-no-drag absolute right-1.5 top-1.5 rounded bg-black/60 p-1 text-white/80 hover:text-white"
          aria-label="remove"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}

      {/* per-cell stream quality (edit mode, dual-stream cameras only): HD = main, SD = sub */}
      {editMode && onSetStreamRole && hdStream(camera) && (
        <button
          onClick={() => onSetStreamRole(streamRole === 'main' ? 'sub' : 'main')}
          title={intl.formatMessage({ id: 'live.quality.toggle' })}
          aria-label="stream quality"
          className={cn(
            'rgl-no-drag absolute bottom-2 left-2 rounded-md border px-2.5 py-1 text-sm font-semibold shadow-sm backdrop-blur transition-colors',
            streamRole === 'main'
              ? 'border-primary bg-primary/90 text-white hover:bg-primary'
              : 'border-white/30 bg-black/60 text-white/90 hover:bg-black/80 hover:text-white',
          )}
        >
          {intl.formatMessage({ id: streamRole === 'main' ? 'live.quality.hd' : 'live.quality.sd' })}
        </button>
      )}

      {/* audio listen toggle — only for cameras with a mic; multiple may be on at once */}
      {canListen && (
        <button
          onClick={onToggleAudio}
          aria-label="listen"
          className={cn(
            'absolute right-2 top-2 rounded bg-black/55 p-1.5 backdrop-blur transition-opacity hover:text-white',
            audioOn ? 'text-primary opacity-100' : 'text-white/80 opacity-0 group-hover:opacity-100',
          )}
        >
          {audioOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
        </button>
      )}

      {canTalk && !editMode && (
        <div className="absolute bottom-2 right-2 opacity-0 transition-opacity group-hover:opacity-100">
          <TalkButton cameraUuid={camera.uuid} />
        </div>
      )}

      {canPtz && !editMode && (
        <div className="absolute bottom-2 left-2 opacity-0 transition-opacity group-hover:opacity-100">
          {showPtz ? (
            <PtzControls cameraUuid={camera.uuid} />
          ) : (
            <button
              onClick={() => setShowPtz(true)}
              className="rounded bg-black/55 p-1.5 text-white/80 backdrop-blur hover:text-white"
              aria-label="ptz"
            >
              <Gamepad2 className="h-4 w-4" />
            </button>
          )}
          {showPtz && (
            <button
              onClick={() => setShowPtz(false)}
              className="mt-1 rounded bg-black/55 px-2 py-0.5 text-[10px] text-white/60"
            >
              닫기
            </button>
          )}
        </div>
      )}
    </div>
  );

  // shell stays in the grid cell; the live content mounts once into portalDiv, which the
  // layout effect above parents into either this shell or the enlarge overlay host
  return (
    <div
      ref={hostRef}
      className={cn(
        'h-full w-full overflow-hidden rounded bg-black',
        !editMode && 'rgl-no-drag',
        spotlight && !enlarged && 'ring-2 ring-primary ring-offset-1 ring-offset-canvas',
      )}
    >
      {createPortal(content, portalDiv)}
    </div>
  );
}
