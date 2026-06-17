import { useIntl } from 'react-intl';

import { Badge } from '@/components/ui/badge';
import { vendorLabel } from '@/pages/cameras/vendor';
import type { ProbeResult } from '@/types/axp';

export function ProbeResultCard({ result }: { result: ProbeResult }) {
  const intl = useIntl();

  if (result.status === 'unauthorized' || result.error === 'unauthorized') {
    return <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {intl.formatMessage({ id: 'camera.probe.unauthorized' })}
    </div>;
  }
  if (result.vendor === 'unknown' || result.error) {
    return <div className="rounded border border-border bg-secondary p-3 text-sm text-muted-foreground">
      {intl.formatMessage({ id: 'camera.probe.failed' })} {result.error ? `(${result.error})` : ''}
    </div>;
  }

  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <div className="flex items-center gap-2">
        <Badge>{vendorLabel(result.vendor)}</Badge>
        {result.ptz_supported && <Badge variant="muted">PTZ</Badge>}
        {result.audio_supported && <Badge variant="muted">Audio</Badge>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">{intl.formatMessage({ id: 'camera.model' })}</dt>
        <dd>{result.model ?? '—'}</dd>
        <dt className="text-muted-foreground">{intl.formatMessage({ id: 'camera.firmware' })}</dt>
        <dd>{result.firmware ?? '—'}</dd>
        <dt className="text-muted-foreground">{intl.formatMessage({ id: 'camera.driver' })}</dt>
        <dd>{result.driver}</dd>
      </dl>
      <div className="space-y-1">
        <div className="text-xs font-medium text-muted-foreground">
          {intl.formatMessage({ id: 'camera.streams' })}
        </div>
        {result.streams.map((s, i) => (
          <div key={i} className="flex items-center justify-between rounded bg-secondary px-2 py-1 text-xs">
            <span className="font-medium">{s.role}</span>
            <span className="text-muted-foreground">
              {s.codec} · {s.width}×{s.height} · {s.fps}fps
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
