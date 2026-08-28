import { CalendarCog } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { EventPolicyMatrix } from '@/pages/events/components/EventPolicyMatrix';
import { RetentionPolicyEditor } from '@/pages/events/components/RetentionPolicyEditor';
import { ScheduleEditor } from '@/pages/events/components/ScheduleEditor';
import { TimelapsePanel } from '@/pages/events/components/TimelapsePanel';
import type { Camera } from '@/types/axp';

type Tab = 'schedule' | 'policies' | 'retention' | 'timelapse';

/** Per-camera recording configuration (schedule / event policies / retention / timelapse),
 *  moved here from the Events page so it lives next to the camera it configures. */
export function RecordingSettingsButton({ camera }: { camera: Camera }) {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();

  const tabs: { key: Tab; show: boolean }[] = [
    { key: 'schedule', show: hasPermission('schedules', 'read') },
    { key: 'policies', show: hasPermission('policies', 'read') },
    { key: 'retention', show: hasPermission('storage', 'read') },
    { key: 'timelapse', show: hasPermission('timelapse', 'read') },
  ];
  const visible = tabs.filter((t) => t.show);

  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>(visible[0]?.key ?? 'schedule');

  if (!visible.length) return null;

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}
        title={intl.formatMessage({ id: 'camera.rec_settings' })} aria-label="recording settings">
        <CalendarCog className="mr-1 h-4 w-4" />
        {intl.formatMessage({ id: 'camera.rec_settings' })}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-auto">
          <DialogHeader>
            <DialogTitle>
              {camera.name} — {intl.formatMessage({ id: 'camera.rec_settings' })}
            </DialogTitle>
          </DialogHeader>

          <div className="flex items-center gap-1 rounded border border-border p-0.5 self-start">
            {visible.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  tab === t.key ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'
                }`}
              >
                {intl.formatMessage({ id: `event.tab.${t.key}` })}
              </button>
            ))}
          </div>

          {tab === 'schedule' ? (
            <ScheduleEditor cameraUuid={camera.uuid} canEdit={hasPermission('schedules', 'update')} />
          ) : tab === 'policies' ? (
            <EventPolicyMatrix cameraUuid={camera.uuid} cameraName={camera.name}
              canEdit={hasPermission('policies', 'update')} />
          ) : tab === 'retention' ? (
            <RetentionPolicyEditor cameraUuid={camera.uuid} canEdit={hasPermission('retention', 'manage')} />
          ) : (
            <TimelapsePanel cameraUuid={camera.uuid} canCreate={hasPermission('timelapse', 'create')} />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
