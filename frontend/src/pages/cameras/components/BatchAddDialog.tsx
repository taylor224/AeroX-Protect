import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Layers } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { batchAddCameras } from '@/pages/cameras/camera.api';
import { vendorLabel } from '@/pages/cameras/vendor';
import type { BatchAddResult } from '@/types/p6';

const VENDORS = ['onvif', 'hikvision', 'dahua', 'hanwha'];

/** Parse "name,host" or "host" per line → camera items. */
function parseHosts(text: string): { name: string; host: string }[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [a, b] = line.split(',').map((s) => s.trim());
      return b ? { name: a, host: b } : { name: a, host: a };
    });
}

export function BatchAddDialog({ onDone }: { onDone: () => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [vendor, setVendor] = useState('onvif');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rtspPort, setRtspPort] = useState('554');
  const [rtspPath, setRtspPath] = useState('/Streaming/Channels/101');
  const [hosts, setHosts] = useState('');
  const [result, setResult] = useState<BatchAddResult | null>(null);

  const items = parseHosts(hosts);

  const addMut = useMutation({
    mutationFn: () =>
      batchAddCameras(
        {
          vendor,
          driver: vendor === 'onvif' ? 'onvif' : vendor,
          username,
          password,
          rtsp_port: Number(rtspPort) || 554,
          streams: [{ role: 'main', rtsp_path: rtspPath }],
        },
        items,
      ),
    onSuccess: (r) => {
      setResult(r);
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      toast.success(intl.formatMessage({ id: 'camera.batch.done' }, { created: r.created, failed: r.failed }));
      if (r.failed === 0) onDone();
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const reset = () => {
    setResult(null);
    setHosts('');
  };

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Layers className="mr-1.5 h-4 w-4" />
        {intl.formatMessage({ id: 'camera.batch' })}
      </Button>

      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) reset();
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'camera.batch.title' })}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-1">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'camera.vendor' })}</Label>
                <select
                  className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                >
                  {VENDORS.map((v) => (
                    <option key={v} value={v}>
                      {vendorLabel(v)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>RTSP Port</Label>
                <Input value={rtspPort} onChange={(e) => setRtspPort(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'camera.username' })}</Label>
                <Input value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>{intl.formatMessage({ id: 'camera.password' })}</Label>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>RTSP Path</Label>
              <Input value={rtspPath} onChange={(e) => setRtspPath(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>{intl.formatMessage({ id: 'camera.batch.hosts' })}</Label>
              <textarea
                className="h-28 w-full rounded border border-input bg-background p-2 text-sm font-mono"
                placeholder={'현관, 192.168.1.10\n주차장, 192.168.1.11\n192.168.1.12'}
                value={hosts}
                onChange={(e) => setHosts(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'camera.batch.hint' }, { count: items.length })}
              </p>
            </div>

            {result && (
              <div className="max-h-40 space-y-1 overflow-auto rounded border border-border p-2 text-xs">
                {result.results.map((r) => (
                  <div key={r.index} className="flex items-center justify-between gap-2">
                    <span className="truncate text-muted-foreground">{r.host}</span>
                    {r.status === 'created' ? (
                      <span className="text-emerald-600">{r.name} ✓</span>
                    ) : (
                      <span className="text-destructive">{r.error}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              {intl.formatMessage({ id: 'common.cancel' })}
            </Button>
            <Button size="sm" disabled={items.length === 0 || addMut.isPending} onClick={() => addMut.mutate()}>
              {intl.formatMessage({ id: 'camera.batch.submit' }, { count: items.length })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
