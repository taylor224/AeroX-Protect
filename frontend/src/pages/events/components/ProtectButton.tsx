import { useMutation } from '@tanstack/react-query';
import { Lock, LockOpen } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { protectRecording } from '@/pages/playback/playback.api';

/** Toggle delete-protection on a specific event's recording (P2 retention lock). Mounted
 *  with key={recordingId} by the caller so its local state resets per selected event. */
export function ProtectButton({ recordingId, initialProtected = false }: { recordingId: string; initialProtected?: boolean }) {
  const intl = useIntl();
  const [on, setOn] = useState(initialProtected);
  const mut = useMutation({
    mutationFn: (next: boolean) => protectRecording(recordingId, next),
    onSuccess: (_, next) => {
      setOn(next);
      toast.success(intl.formatMessage({ id: next ? 'protect.on' : 'protect.off' }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  return (
    <Button
      variant={on ? 'default' : 'outline'}
      size="sm"
      onClick={() => mut.mutate(!on)}
      disabled={mut.isPending}
      title={intl.formatMessage({ id: 'protect.hint' })}
    >
      {on ? <Lock className="mr-1 h-3.5 w-3.5" /> : <LockOpen className="mr-1 h-3.5 w-3.5" />}
      {intl.formatMessage({ id: on ? 'protect.protected' : 'protect.label' })}
    </Button>
  );
}
