import { ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getShareView, shareSegmentUrl, unlockShareView } from '@/pages/share/share.api';
import type { ShareSegment, ShareView } from '@/types/p6';

/** Plays a shared clip's segments sequentially via share-scoped media URLs (no auth). */
function SharePlayer({ token, segments }: { token: string; segments: ShareSegment[] }) {
  const intl = useIntl();
  const [i, setI] = useState(0);
  if (segments.length === 0) {
    return (
      <div className="flex aspect-video w-full items-center justify-center rounded-lg bg-black text-sm text-white/50">
        {intl.formatMessage({ id: 'share.no_footage' })}
      </div>
    );
  }
  const seg = segments[Math.min(i, segments.length - 1)];
  return (
    <video
      key={seg.id}
      src={shareSegmentUrl(token, seg.id)}
      controls
      autoPlay
      playsInline
      className="aspect-video w-full rounded-lg bg-black"
      onEnded={() => setI((x) => (x + 1 < segments.length ? x + 1 : x))}
    />
  );
}

export function ShareViewerPage() {
  const intl = useIntl();
  const { token = '' } = useParams();
  const [view, setView] = useState<ShareView | null>(null);
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [pwError, setPwError] = useState(false);

  useEffect(() => {
    let alive = true;
    void getShareView(token).then((v) => alive && setView(v));
    return () => {
      alive = false;
    };
  }, [token]);

  const unlock = async () => {
    setSubmitting(true);
    setPwError(false);
    const v = await unlockShareView(token, password);
    setSubmitting(false);
    if (v.status === 'password_required') setPwError(true);
    else setView(v);
  };

  const Shell = ({ children }: { children: React.ReactNode }) => (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-white">
      <header className="flex items-center gap-2 px-5 py-3 text-sm font-medium text-white/80">
        <ShieldCheck className="h-4 w-4 text-primary" />
        AeroX Protect
      </header>
      <main className="flex flex-1 items-center justify-center p-4">{children}</main>
    </div>
  );

  if (!view) {
    return (
      <Shell>
        <p className="text-sm text-white/50">{intl.formatMessage({ id: 'common.loading' })}</p>
      </Shell>
    );
  }

  if (view.status === 'password_required') {
    return (
      <Shell>
        <div className="w-full max-w-xs space-y-3 rounded-xl border border-white/10 bg-zinc-900 p-6">
          <h1 className="text-base font-semibold">{intl.formatMessage({ id: 'share.locked' })}</h1>
          <Input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && password && unlock()}
            placeholder={intl.formatMessage({ id: 'share.password' })}
            className="border-white/15 bg-zinc-800 text-white"
          />
          {pwError && <p className="text-xs text-red-400">{intl.formatMessage({ id: 'share.wrong_password' })}</p>}
          <Button className="w-full" disabled={!password || submitting} onClick={unlock}>
            {intl.formatMessage({ id: 'share.unlock' })}
          </Button>
        </div>
      </Shell>
    );
  }

  if (view.status !== 'ok') {
    return (
      <Shell>
        <div className="text-center">
          <p className="text-lg font-semibold">{intl.formatMessage({ id: `share.gone.${view.status}` })}</p>
          <p className="mt-1 text-sm text-white/40">{intl.formatMessage({ id: 'share.gone.desc' })}</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="w-full max-w-3xl space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="truncate text-lg font-semibold">{view.label || view.camera_name}</h1>
          {view.camera_name && <span className="shrink-0 text-sm text-white/50">{view.camera_name}</span>}
        </div>
        <div className="relative">
          <SharePlayer token={token} segments={view.segments ?? []} />
          {view.watermark && (
            <div className="pointer-events-none absolute right-3 top-3 rounded bg-black/40 px-2 py-1 text-[11px] text-white/70">
              AeroX Protect · {view.camera_name}
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}
