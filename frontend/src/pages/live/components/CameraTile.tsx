import { Gamepad2, Plus, Volume2, VolumeX, X } from 'lucide-react';
import { useState } from 'react';

import { useAuthContext } from '@/auth/useAuthContext';
import { useFeatureFlag } from '@/lib/featureFlags';
import { cn } from '@/lib/utils';
import { FisheyeViewer } from '@/pages/live/components/FisheyeViewer';
import { MaskOverlay } from '@/pages/live/components/MaskOverlay';
import { PtzControls } from '@/pages/live/components/PtzControls';
import { TalkButton } from '@/pages/live/components/TalkButton';
import { VideoPlayer } from '@/pages/live/components/VideoPlayer';
import type { Camera, RatioMode } from '@/types/axp';

const DOT: Record<string, string> = {
  online: 'bg-emerald-500',
  offline: 'bg-zinc-400',
  unauthorized: 'bg-red-500',
  error: 'bg-red-500',
  unknown: 'bg-zinc-300',
};

function liveStreamName(camera: Camera): string {
  const s = camera.streams?.find((st) => st.is_default_live) ?? camera.streams?.[0];
  return s?.go2rtc_name ?? `cam_${camera.uuid}_sub`;
}

export function CameraTile({
  camera,
  ratioMode = 'fit',
  editMode = false,
  active = true,
  spotlight = false,
  showName = false,
  audioOn = false,
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
  onToggleAudio?: () => void;
  onRemove?: () => void;
  onClickEmpty?: () => void;
  onEnlarge?: () => void;
}) {
  const { hasPermission } = useAuthContext();
  const talkEnabled = useFeatureFlag('two_way_audio');
  const [showPtz, setShowPtz] = useState(false);

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

  return (
    <div
      onDoubleClick={!editMode ? onEnlarge : undefined}
      className={cn(
        'group relative h-full w-full overflow-hidden rounded bg-black transition-shadow',
        // exempt the tile from react-grid-layout's drag-detection in view mode so its mousedown
        // handling can't swallow the first click of a double-click (drag is edit-mode only)
        !editMode && 'rgl-no-drag',
        spotlight && 'ring-2 ring-primary ring-offset-1 ring-offset-canvas',
        !editMode && onEnlarge && 'cursor-zoom-in',
      )}
    >
      {camera.fisheye ? (
        <FisheyeViewer camera={camera} active={active && !editMode} />
      ) : (
        <VideoPlayer
          go2rtcName={liveStreamName(camera)}
          ratioMode={ratioMode}
          active={active && !editMode}
          muted={!audioOn}
        />
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
}
