import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil, ScanSearch } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { reprobeCamera, updateCamera, type CreateCameraRequest } from '@/pages/cameras/camera.api';
import { vendorLabel } from '@/pages/cameras/vendor';
import type { Camera } from '@/types/axp';

// the three supported camera drivers (vendor API + ONVIF fallback)
const DRIVERS = [
  { value: 'onvif', label: 'ONVIF (표준)' },
  { value: 'isapi', label: 'Hikvision (ISAPI)' },
  { value: 'sunapi', label: 'Hanwha (SUNAPI)' },
];
const VENDORS = ['hikvision', 'hanwha', 'dahua', 'axis', 'reolink', 'uniview', 'onvif', 'unknown'];

type EditForm = {
  name: string;
  host: string;
  vendor: string;
  driver: string;
  onvif_port: string;
  http_port: string;
  rtsp_port: string;
  rtsp_transport: string;
  use_https: boolean;
  is_enabled: boolean;
  live_transcode: boolean;
  username: string;
  password: string;
};

const fromCamera = (c: Camera): EditForm => ({
  name: c.name ?? '',
  host: c.host ?? '',
  vendor: c.vendor ?? 'unknown',
  driver: c.driver ?? 'onvif',
  onvif_port: c.onvif_port?.toString() ?? '',
  http_port: c.http_port?.toString() ?? '',
  rtsp_port: c.rtsp_port?.toString() ?? '',
  rtsp_transport: c.rtsp_transport ?? 'auto',
  use_https: !!c.use_https,
  is_enabled: c.is_enabled !== false,
  live_transcode: !!c.live_transcode,
  username: '',
  password: '',
});

const numOrUndef = (s: string) => (s.trim() === '' ? undefined : Number(s));

export function CameraEditButton({ camera }: { camera: Camera }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<EditForm>(() => fromCamera(camera));
  const [streams, setStreams] = useState(camera.streams ?? []);

  const set = <K extends keyof EditForm>(k: K, v: EditForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  const openDialog = () => {
    setForm(fromCamera(camera));
    setStreams(camera.streams ?? []);
    setOpen(true);
  };

  // auto-detect: re-probe with stored creds → updates vendor/driver + high/low streams server-side
  const probeMut = useMutation({
    mutationFn: () => reprobeCamera(camera.uuid),
    onSuccess: (cam) => {
      setForm((f) => ({ ...f, vendor: cam.vendor ?? f.vendor, driver: cam.driver ?? f.driver }));
      setStreams(cam.streams ?? []);
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      toast.success(intl.formatMessage({ id: 'camera.detected' }, { n: cam.streams?.length ?? 0 }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'camera.detect_failed' })),
  });

  const saveMut = useMutation({
    mutationFn: () => {
      const patch: Partial<CreateCameraRequest> = {
        name: form.name.trim(),
        host: form.host.trim(),
        vendor: form.vendor || 'unknown',
        driver: form.driver || 'onvif',
        onvif_port: numOrUndef(form.onvif_port),
        http_port: numOrUndef(form.http_port),
        rtsp_port: numOrUndef(form.rtsp_port),
        rtsp_transport: form.rtsp_transport,
        use_https: form.use_https,
        is_enabled: form.is_enabled,
        live_transcode: form.live_transcode,
      };
      if (form.username.trim() || form.password) {
        patch.username = form.username.trim();
        patch.password = form.password;
      }
      return updateCamera(camera.uuid, patch);
    },
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'camera.updated' }));
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'camera.create_failed' })),
  });

  const field = (key: keyof EditForm, labelId: string, type = 'text', placeholder?: string) => (
    <label className="space-y-1">
      <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: labelId })}</span>
      <Input type={type} value={form[key] as string} placeholder={placeholder}
        onChange={(e) => set(key, e.target.value as never)} />
    </label>
  );

  const mainS = streams.find((s) => s.role === 'main');
  const subS = streams.find((s) => s.role === 'sub');
  const res = (s?: { width: number | null; height: number | null }) =>
    s?.width && s?.height ? `${s.width}×${s.height}` : '—';

  return (
    <>
      <Button variant="ghost" size="icon" onClick={openDialog}
        title={intl.formatMessage({ id: 'camera.edit' })} aria-label="edit camera">
        <Pencil className="h-4 w-4" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[88vh] max-w-lg overflow-auto">
          <DialogHeader>
            <DialogTitle>{intl.formatMessage({ id: 'camera.edit' })}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {field('name', 'camera.name')}
            <div className="grid grid-cols-2 gap-2">
              {field('host', 'camera.host')}
              {field('rtsp_port', 'camera.rtsp_port', 'number')}
              {field('onvif_port', 'camera.onvif_port', 'number', intl.formatMessage({ id: 'camera.port_http_hint' }))}
              {field('http_port', 'camera.http_port', 'number')}
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.rtsp_transport' })}</span>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={form.rtsp_transport} onChange={(e) => set('rtsp_transport', e.target.value)}>
                  <option value="auto">{intl.formatMessage({ id: 'camera.transport_auto' })}</option>
                  <option value="tcp">TCP</option>
                  <option value="udp">UDP</option>
                </select>
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.driver' })}</span>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={form.driver} onChange={(e) => set('driver', e.target.value)}>
                  {DRIVERS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.vendor' })}</span>
                <select className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
                  value={VENDORS.includes(form.vendor) ? form.vendor : 'unknown'}
                  onChange={(e) => set('vendor', e.target.value)}>
                  {(VENDORS.includes(form.vendor) ? VENDORS : [form.vendor, ...VENDORS]).map((v) => (
                    <option key={v} value={v}>{vendorLabel(v)}</option>
                  ))}
                </select>
              </label>
            </div>

            {/* auto-detect (reprobe) + detected streams */}
            <div className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{intl.formatMessage({ id: 'camera.streams' })}</span>
                <Button variant="outline" size="sm" disabled={probeMut.isPending} onClick={() => probeMut.mutate()}>
                  <ScanSearch className="mr-1 h-3.5 w-3.5" />
                  {intl.formatMessage({ id: 'camera.autodetect' })}
                </Button>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div>{intl.formatMessage({ id: 'camera.stream_high' })}: <span className="text-foreground">{res(mainS)}</span></div>
                <div>{intl.formatMessage({ id: 'camera.stream_low' })}: <span className="text-foreground">{subS ? res(subS) : intl.formatMessage({ id: 'camera.stream_none' })}</span></div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              {field('username', 'camera.username', 'text', intl.formatMessage({ id: 'camera.creds_keep' }))}
              {field('password', 'camera.password', 'password', intl.formatMessage({ id: 'camera.creds_keep' }))}
            </div>
            <label className="flex items-center justify-between rounded-md border border-border px-3 py-2">
              <span className="text-sm">HTTPS</span>
              <Switch checked={form.use_https} onCheckedChange={(v) => set('use_https', v)} />
            </label>
            <label className="flex items-center justify-between rounded-md border border-border px-3 py-2">
              <span className="text-sm">{intl.formatMessage({ id: 'camera.enabled' })}</span>
              <Switch checked={form.is_enabled} onCheckedChange={(v) => set('is_enabled', v)} />
            </label>
            <label className="flex items-center justify-between rounded-md border border-border px-3 py-2">
              <span>
                <span className="text-sm">{intl.formatMessage({ id: 'camera.live_transcode' })}</span>
                <span className="block text-xs text-muted-foreground">{intl.formatMessage({ id: 'camera.live_transcode.desc' })}</span>
              </span>
              <Switch checked={form.live_transcode} onCheckedChange={(v) => set('live_transcode', v)} />
            </label>
            <Button className="w-full" disabled={saveMut.isPending || !form.name.trim() || !form.host.trim()}
              onClick={() => saveMut.mutate()}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
