import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bookmark as BookmarkIcon } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { createBookmark } from '@/pages/events/bookmark.api';

const COLORS = ['#3E6AE1', '#EF4444', '#22C55E', '#F59E0B', '#A855F7'];

/** Adds a bookmark at `atTs` (current playhead) for a camera, optionally linked to a
 *  recording/event and retention-locked. */
export function BookmarkButton({
  cameraUuid,
  atTs,
  recordingId,
  eventId,
  eventLabel,
}: {
  cameraUuid: string;
  atTs: number;
  recordingId?: string | null;
  eventId?: string | null;
  eventLabel?: string | null;
}) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [color, setColor] = useState(COLORS[0]);
  const [lock, setLock] = useState(false);

  const createMut = useMutation({
    mutationFn: () =>
      createBookmark({
        camera_uuid: cameraUuid,
        start_ts: Math.round(atTs),
        label: label.trim(),
        color,
        lock_retention: lock,
        recording_id: recordingId ?? null,
        event_id: eventId ?? null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bookmarks', cameraUuid] });
      toast.success(intl.formatMessage({ id: 'bookmark.saved' }));
      setOpen(false);
      setLabel('');
      setLock(false);
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <BookmarkIcon className="mr-1 h-4 w-4" />
        {intl.formatMessage({ id: 'bookmark.add' })}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'bookmark.add' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="rounded-md bg-secondary/60 px-3 py-2 text-xs text-muted-foreground">
              {eventId
                ? intl.formatMessage({ id: 'bookmark.on_event' }, { label: eventLabel ?? '' })
                : intl.formatMessage({ id: 'bookmark.on_time' })}
            </div>
            <div className="space-y-2">
              <Label>{intl.formatMessage({ id: 'bookmark.label' })}</Label>
              <Input
                autoFocus
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={intl.formatMessage({ id: 'bookmark.label.ph' })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && label.trim()) createMut.mutate();
                }}
              />
            </div>
            <div className="space-y-2">
              <Label>{intl.formatMessage({ id: 'bookmark.color' })}</Label>
              <div className="flex items-center gap-2">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    onClick={() => setColor(c)}
                    aria-label={c}
                    className={`h-6 w-6 rounded-full transition ${
                      color === c ? 'ring-2 ring-foreground ring-offset-2 ring-offset-background' : ''
                    }`}
                    style={{ background: c }}
                  />
                ))}
              </div>
            </div>
            <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
              <div>
                <div className="text-sm font-medium text-foreground">
                  {intl.formatMessage({ id: 'bookmark.lock' })}
                </div>
                <div className="text-xs text-muted-foreground">
                  {intl.formatMessage({ id: 'bookmark.lock.desc' })}
                </div>
              </div>
              <Switch checked={lock} onCheckedChange={setLock} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              {intl.formatMessage({ id: 'common.cancel' })}
            </Button>
            <Button size="sm" disabled={!label.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
