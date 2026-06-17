import type { ScheduleMode } from '@/types/p3';

export const EVENT_TYPE_COLOR: Record<string, string> = {
  motion: '#3E6AE1',
  line_crossing: '#22C55E',
  intrusion: '#EF4444',
  region_enter: '#14B8A6',
  region_exit: '#0EA5E9',
  tamper: '#F59E0B',
  audio: '#A855F7',
  io: '#64748B',
  video_loss: '#DC2626',
  object: '#EC4899',
  loitering: '#F97316',
  count: '#06B6D4',
  occupancy: '#8B5CF6',
  doorbell_call: '#10B981',
  audio_class: '#A855F7',
  smoke: '#DC2626',
  lpr: '#0891B2',
  face: '#DB2777',
  access: '#7C3AED',
  unknown: '#9CA3AF',
};

export function eventColor(type: string): string {
  return EVENT_TYPE_COLOR[type] ?? EVENT_TYPE_COLOR.unknown;
}

export const SCHEDULE_MODE_COLOR: Record<ScheduleMode, string> = {
  continuous: '#3E6AE1',
  event: '#F59E0B',
  motion_only: '#22C55E',
  off: '#3F3F46',
};

/** minute-of-day (0..1440) → "HH:MM" */
export function minToHHMM(min: number): string {
  const h = Math.floor(min / 60) % 24;
  const m = min % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
