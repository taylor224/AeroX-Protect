import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Minus, Plus } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';
import { ptzCommand } from '@/pages/cameras/camera.api';

const SPEED = 0.6;

/** Compact PTZ pad: hold a direction → continuous move, release → stop. */
export function PtzControls({ cameraUuid }: { cameraUuid: string }) {
  const [busy, setBusy] = useState(false);

  const move = (pan: number, tilt: number, zoom: number) => {
    setBusy(true);
    void ptzCommand(cameraUuid, { action: 'continuous', pan, tilt, zoom, speed: SPEED }).catch(() => {});
  };
  const stop = () => {
    setBusy(false);
    void ptzCommand(cameraUuid, { action: 'stop' }).catch(() => {});
  };

  const Pad = ({ pan, tilt, zoom, children, className }: {
    pan: number; tilt: number; zoom: number; children: React.ReactNode; className?: string;
  }) => (
    <button
      className={cn(
        'flex h-8 w-8 items-center justify-center rounded bg-white/10 text-white transition-colors hover:bg-white/20',
        className,
      )}
      onPointerDown={() => move(pan, tilt, zoom)}
      onPointerUp={stop}
      onPointerLeave={() => busy && stop()}
    >
      {children}
    </button>
  );

  return (
    <div className="flex items-center gap-3 rounded-lg bg-black/55 p-2 backdrop-blur">
      <div className="grid grid-cols-3 grid-rows-3 gap-1">
        <span />
        <Pad pan={0} tilt={SPEED} zoom={0}><ChevronUp className="h-4 w-4" /></Pad>
        <span />
        <Pad pan={-SPEED} tilt={0} zoom={0}><ChevronLeft className="h-4 w-4" /></Pad>
        <span className="flex items-center justify-center text-[10px] text-white/40">PTZ</span>
        <Pad pan={SPEED} tilt={0} zoom={0}><ChevronRight className="h-4 w-4" /></Pad>
        <span />
        <Pad pan={0} tilt={-SPEED} zoom={0}><ChevronDown className="h-4 w-4" /></Pad>
        <span />
      </div>
      <div className="flex flex-col gap-1">
        <Pad pan={0} tilt={0} zoom={SPEED}><Plus className="h-4 w-4" /></Pad>
        <Pad pan={0} tilt={0} zoom={-SPEED}><Minus className="h-4 w-4" /></Pad>
      </div>
    </div>
  );
}
