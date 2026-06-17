import { useIntl } from 'react-intl';

import { CameraThumbnail } from '@/components/CameraThumbnail';
import { Card } from '@/components/ui/card';
import { CameraHealthBadge } from '@/pages/cameras/components/CameraHealthBadge';
import type { Camera } from '@/types/axp';

/** Camera chooser shown when entering Events with no camera selected — thumbnail per camera. */
export function CameraPickGrid({
  cameras,
  onPick,
}: {
  cameras: Camera[];
  onPick: (uuid: string) => void;
}) {
  const intl = useIntl();

  if (cameras.length === 0) {
    return (
      <Card className="p-10 text-center text-sm text-muted-foreground">
        {intl.formatMessage({ id: 'camera.empty' })}
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {cameras.map((c) => (
        <button
          key={c.uuid}
          onClick={() => onPick(c.uuid)}
          className="group overflow-hidden rounded-xl border border-border bg-card text-left transition hover:border-primary hover:shadow-sm"
        >
          <CameraThumbnail cameraUuid={c.uuid} status={c.status} className="aspect-video w-full" iconClassName="h-7 w-7" />
          <div className="flex items-center justify-between gap-2 px-3 py-2.5">
            <span className="truncate text-sm font-medium text-foreground">{c.name}</span>
            <CameraHealthBadge status={c.status} />
          </div>
        </button>
      ))}
    </div>
  );
}
