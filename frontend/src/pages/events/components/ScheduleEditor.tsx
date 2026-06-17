import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { getSchedule, replaceSchedule } from '@/pages/events/events.api';
import { SCHEDULE_MODE_COLOR } from '@/pages/events/eventMeta';
import { SCHEDULE_MODES, type ScheduleMode, type ScheduleRule } from '@/types/p3';

const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']; // dow 0..6 (KST)
const HOURS = Array.from({ length: 24 }, (_, i) => i);
const DEFAULT_MODE: ScheduleMode = 'continuous';

function rulesToGrid(rules: ScheduleRule[]): ScheduleMode[][] {
  const grid: ScheduleMode[][] = DAY_KEYS.map(() => HOURS.map(() => DEFAULT_MODE));
  // higher priority overwrites lower → apply ascending
  [...rules]
    .sort((a, b) => a.priority - b.priority)
    .forEach((r) => {
      if (r.day_of_week < 0 || r.day_of_week > 6) return;
      for (let h = 0; h < 24; h++) {
        const mid = h * 60;
        if (mid >= r.start_min && mid < r.end_min) grid[r.day_of_week][h] = r.mode;
      }
    });
  return grid;
}

function gridToRules(grid: ScheduleMode[][]): ScheduleRule[] {
  const rules: ScheduleRule[] = [];
  grid.forEach((row, dow) => {
    let h = 0;
    while (h < 24) {
      const mode = row[h];
      if (mode === DEFAULT_MODE) {
        h++;
        continue; // continuous is the implicit default — no rule needed
      }
      let end = h + 1;
      while (end < 24 && row[end] === mode) end++;
      rules.push({ day_of_week: dow, start_min: h * 60, end_min: end * 60, mode, priority: 0 });
      h = end;
    }
  });
  return rules;
}

export function ScheduleEditor({ cameraUuid, canEdit }: { cameraUuid: string; canEdit: boolean }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [brush, setBrush] = useState<ScheduleMode>('off');
  const [grid, setGrid] = useState<ScheduleMode[][]>(() => DAY_KEYS.map(() => HOURS.map(() => DEFAULT_MODE)));
  const [dirty, setDirty] = useState(false);
  // Excel-style rectangular drag: anchor at mousedown, drag to a second cell → the whole
  // day×hour rectangle is painted. While dragging we preview over a snapshot; commit on mouseup.
  const [painting, setPainting] = useState(false);
  const [anchor, setAnchor] = useState<{ dow: number; h: number } | null>(null);
  const [hover, setHover] = useState<{ dow: number; h: number } | null>(null);
  const baseGrid = useRef<ScheduleMode[][]>(grid);

  const scheduleQuery = useQuery({
    queryKey: ['schedule', cameraUuid],
    queryFn: () => getSchedule(cameraUuid),
    enabled: !!cameraUuid,
  });

  useEffect(() => {
    if (scheduleQuery.data) {
      setGrid(rulesToGrid(scheduleQuery.data));
      setDirty(false);
    }
  }, [scheduleQuery.data]);

  const rect = useMemo(() => {
    if (!anchor || !hover) return null;
    return {
      d0: Math.min(anchor.dow, hover.dow), d1: Math.max(anchor.dow, hover.dow),
      h0: Math.min(anchor.h, hover.h), h1: Math.max(anchor.h, hover.h),
    };
  }, [anchor, hover]);

  const applyRect = (base: ScheduleMode[][]) => {
    const next = base.map((r) => [...r]);
    if (rect) {
      for (let d = rect.d0; d <= rect.d1; d++)
        for (let x = rect.h0; x <= rect.h1; x++) next[d][x] = brush;
    }
    return next;
  };

  // grid shown to the user: live rectangle preview while dragging, else the committed grid
  const displayGrid = painting && rect ? applyRect(baseGrid.current) : grid;

  // commit the painted rectangle on mouse release (anywhere on the page)
  useEffect(() => {
    const up = () => {
      if (painting && rect) {
        setGrid(applyRect(baseGrid.current));
        setDirty(true);
      }
      setPainting(false);
      setAnchor(null);
      setHover(null);
    };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [painting, rect, brush]);

  const saveMut = useMutation({
    mutationFn: () => replaceSchedule(cameraUuid, gridToRules(grid)),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'schedule.saved' }));
      setDirty(false);
      void queryClient.invalidateQueries({ queryKey: ['schedule', cameraUuid] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const startPaint = (dow: number, hour: number) => {
    if (!canEdit) return;
    baseGrid.current = grid;
    setAnchor({ dow, h: hour });
    setHover({ dow, h: hour });
    setPainting(true);
  };
  const enterCell = (dow: number, hour: number) => {
    if (painting) setHover({ dow, h: hour });
  };

  const ruleCount = useMemo(() => gridToRules(grid).length, [grid]);

  return (
    <Card className="space-y-3 bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'schedule.brush' })}</span>
        {SCHEDULE_MODES.map((m) => {
          const sel = brush === m;
          return (
            <button
              key={m}
              onClick={() => setBrush(m)}
              className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition ${
                sel ? 'border-transparent text-white shadow-sm ring-2 ring-white/60' : 'border-border text-foreground hover:bg-secondary'
              }`}
              style={sel ? { background: SCHEDULE_MODE_COLOR[m] } : undefined}
            >
              {sel ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SCHEDULE_MODE_COLOR[m] }} />
              )}
              {intl.formatMessage({ id: `schedule.mode.${m}` })}
            </button>
          );
        })}
        <div className="flex-1" />
        <span className="text-xs text-muted-foreground">
          {intl.formatMessage({ id: 'schedule.rule_count' }, { count: ruleCount })}
        </span>
        {canEdit && (
          <Button size="sm" disabled={!dirty || saveMut.isPending} onClick={() => saveMut.mutate()}>
            {intl.formatMessage({ id: 'common.save' })}
          </Button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] table-fixed select-none border-separate border-spacing-0.5 text-[10px]">
          <colgroup>
            <col className="w-12" />
            {HOURS.map((h) => (
              <col key={h} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="w-12" />
              {HOURS.map((h) => (
                <th key={h} className="overflow-visible text-center font-normal text-muted-foreground">
                  {h % 3 === 0 ? h : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAY_KEYS.map((dk, dow) => (
              <tr key={dk}>
                <td className="pr-1 text-right text-muted-foreground">{intl.formatMessage({ id: `schedule.day.${dk}` })}</td>
                {HOURS.map((h) => (
                  <td key={h} className="p-0">
                    <div
                      onMouseDown={(e) => { e.preventDefault(); startPaint(dow, h); }}
                      onMouseEnter={() => enterCell(dow, h)}
                      title={`${intl.formatMessage({ id: `schedule.day.${dk}` })} ${String(h).padStart(2, '0')}:00`}
                      className={`h-6 rounded-sm ${canEdit ? 'cursor-pointer' : ''}`}
                      style={{ background: SCHEDULE_MODE_COLOR[displayGrid[dow][h]] }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted-foreground">{intl.formatMessage({ id: 'schedule.hint' })}</p>
    </Card>
  );
}
