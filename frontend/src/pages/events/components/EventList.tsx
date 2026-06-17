import { useIntl } from 'react-intl';

import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { eventColor } from '@/pages/events/eventMeta';
import type { AxpEvent } from '@/types/p3';

function ActionBadge({ action }: { action: string | null }) {
  const intl = useIntl();
  if (!action) return <span className="text-muted-foreground">—</span>;
  const base = action.split(':')[0];
  const variant = base === 'record' ? 'success' : base === 'discard' ? 'muted' : 'default';
  return <Badge variant={variant}>{intl.formatMessage({ id: `policy.action.${base}`, defaultMessage: action })}</Badge>;
}

export function EventList({
  events,
  selectedId,
  onSelect,
}: {
  events: AxpEvent[];
  selectedId: string | null;
  onSelect: (ev: AxpEvent) => void;
}) {
  const intl = useIntl();
  const { locale } = useTranslation();

  if (events.length === 0) {
    return <div className="p-8 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'event.empty' })}</div>;
  }

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{intl.formatMessage({ id: 'event.col.time' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'event.col.type' })}</TableHead>
            <TableHead className="text-right">{intl.formatMessage({ id: 'event.col.score' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'event.col.action' })}</TableHead>
            <TableHead>{intl.formatMessage({ id: 'event.col.clip' })}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((ev) => (
            <TableRow
              key={ev.id}
              onClick={() => onSelect(ev)}
              className={`cursor-pointer ${selectedId === ev.id ? 'bg-secondary' : ''}`}
            >
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatDateTime(ev.start_ts, locale)}
              </TableCell>
              <TableCell>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: eventColor(ev.type) }} />
                  {intl.formatMessage({ id: `event.type.${ev.type}`, defaultMessage: ev.type })}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{ev.score ?? '—'}</TableCell>
              <TableCell>
                <ActionBadge action={ev.policy_action} />
              </TableCell>
              <TableCell>
                {ev.recording_id ? (
                  <Badge variant="success">{intl.formatMessage({ id: 'event.has_clip' })}</Badge>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
