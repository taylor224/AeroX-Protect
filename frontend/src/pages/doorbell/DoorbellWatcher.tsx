import { useQuery } from '@tanstack/react-query';
import { Bell } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useIntl } from 'react-intl';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useFeatureFlag } from '@/lib/featureFlags';
import { listCameras } from '@/pages/cameras/camera.api';
import { listEvents } from '@/pages/events/events.api';
import { TalkButton } from '@/pages/live/components/TalkButton';
import { snapshotUrl } from '@/pages/live/live.api';

const WINDOW = 30_000;

/** App-shell watcher: polls recent `doorbell_call` events and pops a call modal (answer via
 *  two-way audio). Mounted once in DashboardLayout. */
export function DoorbellWatcher() {
  const intl = useIntl();
  const enabled = useFeatureFlag('doorbell');
  const dismissed = useRef<Set<string>>(new Set());
  const [active, setActive] = useState<{ eventId: string; uuid?: string; name?: string } | null>(null);

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras(), enabled });
  const cameraById = useMemo(
    () => new Map((camerasQuery.data?.items ?? []).map((c) => [String(c.id), c])),
    [camerasQuery.data],
  );

  const eventsQuery = useQuery({
    queryKey: ['doorbell-events'],
    queryFn: () => listEvents({ types: ['doorbell_call'], start: Date.now() - WINDOW, end: Date.now() }),
    enabled,
    refetchInterval: 4000,
  });

  useEffect(() => {
    if (active) return;
    const fresh = (eventsQuery.data?.items ?? []).find((e) => !dismissed.current.has(e.id));
    if (fresh) {
      const cam = cameraById.get(String(fresh.camera_id));
      setActive({ eventId: fresh.id, uuid: cam?.uuid, name: cam?.name });
    }
  }, [eventsQuery.data, active, cameraById]);

  if (!enabled || !active) return null;
  const dismiss = () => {
    dismissed.current.add(active.eventId);
    setActive(null);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && dismiss()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5 animate-pulse text-primary" />
            {intl.formatMessage({ id: 'doorbell.calling' }, { name: active.name ?? '' })}
          </DialogTitle>
        </DialogHeader>
        {active.uuid && (
          <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
            <img
              src={snapshotUrl(active.uuid)}
              alt={active.name ?? ''}
              className="h-full w-full object-cover"
              onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
            />
          </div>
        )}
        <div className="flex items-center justify-end gap-2">
          {active.uuid && <TalkButton cameraUuid={active.uuid} />}
          <Button variant="ghost" size="sm" onClick={dismiss}>
            {intl.formatMessage({ id: 'doorbell.dismiss' })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
