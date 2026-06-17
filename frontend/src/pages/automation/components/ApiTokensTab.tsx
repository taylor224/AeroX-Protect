import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useConfirm } from '@/components/ConfirmProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTranslation } from '@/i18n/TranslationProvider';
import { formatDateTime } from '@/lib/format';
import { createApiToken, listApiTokens, revokeApiToken } from '@/pages/automation/automation.api';

const SCOPE_RESOURCES = ['events', 'state', 'cameras', 'snapshots'];

export function ApiTokensTab() {
  const intl = useIntl();
  const confirm = useConfirm();
  const { locale } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['events', 'state']);
  const [plaintext, setPlaintext] = useState<string | null>(null);

  const tokensQuery = useQuery({ queryKey: ['api-tokens'], queryFn: listApiTokens });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['api-tokens'] });

  const createMut = useMutation({
    mutationFn: () => createApiToken(name || 'token', Object.fromEntries(scopes.map((s) => [s, ['read']]))),
    onSuccess: (t) => { setPlaintext(t.token); setName(''); invalidate(); },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });
  const revokeMut = useMutation({ mutationFn: (uuid: string) => revokeApiToken(uuid), onSuccess: invalidate });

  const tokens = tokensQuery.data ?? [];
  const toggle = (s: string) => setScopes((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.tokens_subtitle' })}</p>
        <Button size="sm" onClick={() => { setPlaintext(null); setOpen(true); }}>
          <Plus className="mr-1 h-4 w-4" />{intl.formatMessage({ id: 'auto.add_token' })}
        </Button>
      </div>
      <Card className="divide-y divide-border bg-card">
        {tokens.map((t) => (
          <div key={t.uuid} className="flex items-center justify-between px-3 py-2 text-sm">
            <span>
              {t.name} <code className="text-xs text-muted-foreground">{t.token_prefix}…</code>{' '}
              {Object.keys(t.scopes || {}).map((s) => <Badge key={s} variant="muted">{s}</Badge>)}
              {t.revoked_at && <Badge variant="danger">revoked</Badge>}
            </span>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {t.last_used_at ? formatDateTime(t.last_used_at, locale) : '—'}
              {!t.revoked_at && (
                <Button variant="ghost" size="icon" onClick={async () => {
                  if (await confirm({
                    title: intl.formatMessage({ id: 'confirm.revoke.title' }),
                    description: intl.formatMessage({ id: 'confirm.revoke.desc' }),
                    confirmLabel: intl.formatMessage({ id: 'common.revoke' }),
                    destructive: true,
                  }))
                    revokeMut.mutate(t.uuid);
                }}><Trash2 className="h-4 w-4 text-red-400" /></Button>
              )}
            </div>
          </div>
        ))}
        {tokens.length === 0 && <div className="p-4 text-center text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.no_tokens' })}</div>}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{intl.formatMessage({ id: 'auto.add_token' })}</DialogTitle></DialogHeader>
          {plaintext ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">{intl.formatMessage({ id: 'auto.token_once' })}</p>
              <code className="block break-all rounded bg-black/40 p-2 text-xs text-emerald-300">{plaintext}</code>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="space-y-1.5"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Home Assistant" /></div>
              <div className="space-y-1.5">
                <Label>Scopes</Label>
                <div className="flex flex-wrap gap-1.5">
                  {SCOPE_RESOURCES.map((s) => (
                    <button key={s} onClick={() => toggle(s)}
                      className={`rounded-full border px-2.5 py-1 text-xs ${scopes.includes(s) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
                      {s}:read
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>{intl.formatMessage({ id: 'common.cancel' })}</Button>
            {!plaintext && <Button disabled={createMut.isPending} onClick={() => createMut.mutate()}>{intl.formatMessage({ id: 'common.create' })}</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
