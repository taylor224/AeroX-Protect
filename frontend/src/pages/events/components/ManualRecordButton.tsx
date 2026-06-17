import { useMutation } from '@tanstack/react-query';
import { Circle, Square } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { manualStart, manualStop } from '@/pages/playback/playback.api';

const QUICK_MIN = [1, 5, 10, 30];

/** Manual recording control. Stop button while a manual recording is active; otherwise a
 *  dialog to pick a fixed duration (quick presets, or a custom amount in minutes/hours) or
 *  record open-ended until manually stopped. */
export function ManualRecordButton({
  cameraUuid,
  active,
  onChanged,
}: {
  cameraUuid: string;
  active: { id: string } | null | undefined;
  onChanged: () => void;
}) {
  const intl = useIntl();
  const [open, setOpen] = useState(false);
  const [unit, setUnit] = useState<'min' | 'hour'>('min');
  const [amount, setAmount] = useState('5');

  const startMut = useMutation({
    mutationFn: (durationS?: number) => manualStart(cameraUuid, durationS),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'recording.manual_started' }));
      setOpen(false);
      onChanged();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const stopMut = useMutation({
    mutationFn: () => manualStop(cameraUuid, active!.id),
    onSuccess: onChanged,
  });

  if (active) {
    return (
      <Button variant="outline" size="sm" className="text-red-500" onClick={() => stopMut.mutate()} disabled={stopMut.isPending}>
        <Square className="mr-1 h-3.5 w-3.5 fill-current" />
        {intl.formatMessage({ id: 'recording.manual_stop' })}
      </Button>
    );
  }

  const customSeconds = Math.max(0, Number(amount) || 0) * (unit === 'hour' ? 3600 : 60);

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Circle className="mr-1 h-3.5 w-3.5 fill-red-500 text-red-500" />
        {intl.formatMessage({ id: 'recording.manual_start' })}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'recording.manual_title' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'recording.manual_pick' })}</p>
            <div className="grid grid-cols-4 gap-2">
              {QUICK_MIN.map((m) => (
                <Button key={m} variant="outline" size="sm" disabled={startMut.isPending} onClick={() => startMut.mutate(m * 60)}>
                  {intl.formatMessage({ id: 'recording.min' }, { n: m })}
                </Button>
              ))}
            </div>
            <div className="flex items-end gap-2">
              <Input
                type="number"
                min={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-24"
              />
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value as 'min' | 'hour')}
                className="h-9 rounded border border-input bg-background px-2 text-sm"
              >
                <option value="min">{intl.formatMessage({ id: 'recording.unit_min' })}</option>
                <option value="hour">{intl.formatMessage({ id: 'recording.unit_hour' })}</option>
              </select>
              <Button size="sm" disabled={startMut.isPending || customSeconds < 5} onClick={() => startMut.mutate(customSeconds)}>
                {intl.formatMessage({ id: 'recording.manual_start' })}
              </Button>
            </div>
            <Button variant="ghost" size="sm" className="w-full" disabled={startMut.isPending} onClick={() => startMut.mutate(undefined)}>
              {intl.formatMessage({ id: 'recording.manual_open' })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
