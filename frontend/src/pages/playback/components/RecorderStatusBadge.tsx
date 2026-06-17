import { cn } from '@/lib/utils';
import type { RecorderHealth } from '@/types/p2';

const MAP: Record<string, { dot: string; label: string }> = {
  recording: { dot: 'bg-emerald-500', label: '녹화 중' },
  starting: { dot: 'bg-amber-400', label: '시작 중' },
  reconnecting: { dot: 'bg-amber-400', label: '재연결' },
  error: { dot: 'bg-red-500', label: '오류' },
  stopped: { dot: 'bg-zinc-400', label: '중지' },
};

export function RecorderStatusBadge({ health }: { health?: RecorderHealth | null }) {
  const state = health?.state ?? 'stopped';
  const info = MAP[state] ?? MAP.stopped;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-white/80">
      <span className={cn('h-2 w-2 rounded-full', info.dot)} />
      {info.label}
    </span>
  );
}
