import type { Locale } from '@/i18n/TranslationProvider';

/** Epoch-ms → KST time-of-day, fixed 24-hour clock (timeline ticks/tooltips). */
export function formatTime24(epochMs: number, withSeconds = false): string {
  return new Date(epochMs).toLocaleTimeString('en-GB', {
    timeZone: 'Asia/Seoul',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  });
}

/** Epoch-ms (stored UTC) → KST display string (PLAN §12.1: display KST). */
export function formatDateTime(epochMs: number | null | undefined, locale: Locale = 'ko'): string {
  if (!epochMs) return '—';
  return new Date(epochMs).toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
