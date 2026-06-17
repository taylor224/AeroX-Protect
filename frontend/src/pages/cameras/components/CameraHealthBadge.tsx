import { useIntl } from 'react-intl';

import { cn } from '@/lib/utils';
import type { CameraStatus } from '@/types/axp';

const DOT: Record<CameraStatus, string> = {
  online: 'bg-emerald-500',
  offline: 'bg-zinc-400',
  unauthorized: 'bg-red-500',
  error: 'bg-red-500',
  unknown: 'bg-zinc-300',
};

export function CameraHealthBadge({ status }: { status: CameraStatus }) {
  const intl = useIntl();
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={cn('h-2 w-2 rounded-full', DOT[status])} />
      {intl.formatMessage({ id: `camera.status.${status}` })}
    </span>
  );
}
