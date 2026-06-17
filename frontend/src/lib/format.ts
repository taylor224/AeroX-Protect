import type { Locale } from '@/i18n/TranslationProvider';

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
