import { useMutation, useQuery } from '@tanstack/react-query';
import { Check, Copy, Share2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { getGeneralSettings } from '@/pages/settings.api';
import { createShareLink, shareUrl } from '@/pages/share/share.api';

const DAY = 86_400;
const EXPIRY = [
  { key: '1d', s: DAY },
  { key: '7d', s: 7 * DAY },
  { key: '30d', s: 30 * DAY },
];

/** Creates a public share link for an event clip; surfaces the one-time URL to copy. */
export function ShareLinkButton({ eventId }: { eventId: string }) {
  const intl = useIntl();
  const [open, setOpen] = useState(false);
  const [expiry, setExpiry] = useState(7 * DAY);
  const [withPassword, setWithPassword] = useState(false);
  const [password, setPassword] = useState('');
  const [maxViews, setMaxViews] = useState('');
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // configured public base URL (Settings → general); falls back to the browser origin
  const settingsQuery = useQuery({ queryKey: ['general-settings'], queryFn: getGeneralSettings });

  const createMut = useMutation({
    mutationFn: () =>
      createShareLink({
        kind: 'event',
        event_id: eventId,
        expires_in_s: expiry,
        password: withPassword && password ? password : undefined,
        max_views: maxViews ? Number(maxViews) : null,
      }),
    onSuccess: (link) => setUrl(shareUrl(link.path, settingsQuery.data?.public_base_url)),
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const copy = async () => {
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const reset = () => {
    setUrl(null);
    setPassword('');
    setWithPassword(false);
    setMaxViews('');
    setCopied(false);
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Share2 className="mr-1 h-4 w-4" />
        {intl.formatMessage({ id: 'share.button' })}
      </Button>

      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) reset();
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'share.title' })}</DialogTitle>
          </DialogHeader>

          {url ? (
            <div className="space-y-3 py-1">
              <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'share.ready' })}</p>
              <div className="flex items-center gap-2">
                <Input readOnly value={url} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
                <Button size="icon" variant="outline" onClick={copy} aria-label="copy">
                  {copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-xs text-amber-600">{intl.formatMessage({ id: 'share.once' })}</p>
            </div>
          ) : (
            <div className="space-y-4 py-1">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'share.expiry' })}</Label>
                <div className="flex items-center gap-1 rounded border border-border p-0.5">
                  {EXPIRY.map((e) => (
                    <button
                      key={e.key}
                      onClick={() => setExpiry(e.s)}
                      className={`flex-1 rounded px-2 py-1 text-sm transition-colors ${
                        expiry === e.s ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'
                      }`}
                    >
                      {intl.formatMessage({ id: `share.expiry.${e.key}` })}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'share.max_views' })}</Label>
                <Input
                  type="number"
                  value={maxViews}
                  onChange={(e) => setMaxViews(e.target.value)}
                  placeholder="∞"
                />
              </div>
              <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">
                    {intl.formatMessage({ id: 'share.password' })}
                  </div>
                  {withPassword && (
                    <Input
                      className="mt-2"
                      type="text"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={intl.formatMessage({ id: 'share.password.ph' })}
                    />
                  )}
                </div>
                <Switch checked={withPassword} onCheckedChange={setWithPassword} />
              </div>
            </div>
          )}

          <DialogFooter>
            {url ? (
              <Button size="sm" onClick={() => setOpen(false)}>
                {intl.formatMessage({ id: 'common.close' })}
              </Button>
            ) : (
              <>
                <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                  {intl.formatMessage({ id: 'common.cancel' })}
                </Button>
                <Button
                  size="sm"
                  disabled={createMut.isPending || (withPassword && !password)}
                  onClick={() => createMut.mutate()}
                >
                  {intl.formatMessage({ id: 'share.create' })}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
