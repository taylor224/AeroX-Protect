import { Radar } from 'lucide-react';
import { useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ProbeResultCard } from '@/pages/cameras/components/ProbeResultCard';
import { createCamera, discoverOnvif, probeCamera } from '@/pages/cameras/camera.api';
import type { DiscoveredDevice, ProbeResult } from '@/types/axp';

/** ONVIF advertises its service over the first xaddr, e.g. http://192.0.2.5:8000/onvif/… */
function onvifPortFromXaddrs(xaddrs: string[]): string {
  for (const x of xaddrs) {
    try {
      const p = new URL(x).port;
      if (p) return p;
    } catch {
      /* ignore */
    }
  }
  return '80';
}

interface ConnForm {
  host: string;
  http_port: string;
  onvif_port: string;
  rtsp_port: string;
  channel: string;
  username: string;
  password: string;
  use_https: boolean;
}

const INITIAL: ConnForm = {
  host: '',
  http_port: '80',
  onvif_port: '80',
  rtsp_port: '554',
  channel: '1',
  username: '',
  password: '',
  use_https: false,
};

export function CameraAddWizard({ onCreated }: { onCreated: () => void }) {
  const intl = useIntl();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ConnForm>(INITIAL);
  const [probing, setProbing] = useState(false);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [devices, setDevices] = useState<DiscoveredDevice[] | null>(null); // null = not scanned yet

  const reset = () => {
    setForm(INITIAL);
    setResult(null);
    setName('');
    setDevices(null);
  };

  const onDiscover = async () => {
    setDiscovering(true);
    try {
      setDevices(await discoverOnvif());
    } catch {
      toast.error(intl.formatMessage({ id: 'discovery.failed' }));
      setDevices([]);
    } finally {
      setDiscovering(false);
    }
  };

  const pickDevice = (d: DiscoveredDevice) => {
    setForm((f) => ({
      ...f,
      host: d.host,
      onvif_port: onvifPortFromXaddrs(d.xaddrs),
      ...(d.http_port ? { http_port: String(d.http_port) } : {}),
    }));
    if (!name && (d.model || d.name)) setName(d.model ?? d.name ?? '');
    setResult(null);
    setDevices(null); // collapse the list; user fills credentials + probes next
  };

  const conn = () => ({
    host: form.host.trim(),
    http_port: Number(form.http_port) || 80,
    onvif_port: Number(form.onvif_port) || 80,
    rtsp_port: Number(form.rtsp_port) || 554,
    channel: Number(form.channel) || 1,
    username: form.username,
    password: form.password,
    use_https: form.use_https,
  });

  const onProbe = async () => {
    if (!form.host.trim()) return;
    setProbing(true);
    setResult(null);
    try {
      const r = await probeCamera(conn());
      setResult(r);
      if (r.vendor !== 'unknown' && !r.error) {
        if (!name) setName(r.model ?? form.host);
        // the device tells us the real RTSP port (e.g. a non-default 10554) — adopt it
        if (r.detected_rtsp_port) setForm((f) => ({ ...f, rtsp_port: String(r.detected_rtsp_port) }));
      }
    } catch {
      toast.error(intl.formatMessage({ id: 'camera.probe.failed' }));
    } finally {
      setProbing(false);
    }
  };

  const probeOk = !!result && result.vendor !== 'unknown' && !result.error;
  const canRegister = probeOk && !!name.trim();

  const onRegister = async () => {
    if (!result || !canRegister) return;
    setSaving(true);
    try {
      await createCamera({
        ...conn(),
        name: name.trim(),
        vendor: result.vendor,
        driver: result.driver,
        model: result.model,
        firmware: result.firmware,
        serial: result.serial,
        ptz_supported: result.ptz_supported,
        audio_supported: result.audio_supported,
        capabilities: result.capabilities,
        streams: result.streams,
      });
      toast.success(intl.formatMessage({ id: 'camera.created' }));
      setOpen(false);
      reset();
      onCreated();
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status;
      toast.error(intl.formatMessage({ id: status === 409 ? 'camera.duplicate' : 'camera.create_failed' }));
    } finally {
      setSaving(false);
    }
  };

  const field = (key: keyof ConnForm, labelId: string, type = 'text') => (
    <div className="space-y-1.5">
      <Label>{intl.formatMessage({ id: labelId })}</Label>
      <Input
        type={type}
        value={String(form[key])}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>{intl.formatMessage({ id: 'camera.add' })}</Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{intl.formatMessage({ id: 'camera.add' })}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {/* name can be filled in upfront; discovery/probe only auto-fill it when left blank */}
          <div className="space-y-1.5">
            <Label>{intl.formatMessage({ id: 'camera.name' })}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={intl.formatMessage({ id: 'camera.name_placeholder' })}
            />
          </div>

          {/* ONVIF network auto-discovery (WS-Discovery multicast) */}
          <div className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium">{intl.formatMessage({ id: 'discovery.title' })}</p>
                <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'discovery.hint' })}</p>
              </div>
              <Button variant="outline" size="sm" onClick={onDiscover} disabled={discovering}>
                <Radar className="mr-1 h-3.5 w-3.5" />
                {intl.formatMessage({ id: discovering ? 'discovery.scanning' : 'discovery.scan' })}
              </Button>
            </div>
            {devices && devices.length > 0 && (
              <div className="mt-2 max-h-44 space-y-1 overflow-auto">
                {devices.map((d) => (
                  <button key={d.host} onClick={() => pickDevice(d)}
                    className="w-full rounded border border-border px-2.5 py-1.5 text-left transition hover:border-primary">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{d.name ?? d.model ?? d.host}</span>
                      {d.source && (
                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                          {d.source}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {[d.manufacturer, d.model].filter(Boolean).join(' ') || '—'} · {d.host}
                    </div>
                  </button>
                ))}
              </div>
            )}
            {devices && devices.length === 0 && (
              <p className="mt-2 text-xs text-muted-foreground">{intl.formatMessage({ id: 'discovery.none' })}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            {field('host', 'camera.host')}
            {field('http_port', 'camera.http_port')}
            {field('username', 'camera.username')}
            {field('password', 'camera.password', 'password')}
          </div>

          {/* RTSP port defaults to 554; channel only matters for multi-channel DVR/NVR devices
              (default 1 for direct IP cameras). Both live here so the common case stays simple —
              the probe also auto-fills rtsp_port when the device advertises a non-default one. */}
          <details className="rounded-md border border-border px-3 py-2">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              {intl.formatMessage({ id: 'camera.advanced' })}
            </summary>
            <div className="mt-2 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                {field('rtsp_port', 'camera.rtsp_port')}
                {field('channel', 'camera.channel')}
              </div>
              <label className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <span className="text-sm">HTTPS</span>
                <Switch
                  checked={form.use_https}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, use_https: v }))}
                />
              </label>
            </div>
          </details>

          <Button variant="outline" onClick={onProbe} disabled={probing || !form.host.trim()}>
            {probing
              ? intl.formatMessage({ id: 'camera.probing' })
              : intl.formatMessage({ id: 'camera.probe' })}
          </Button>

          {result && <ProbeResultCard result={result} />}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {intl.formatMessage({ id: 'common.cancel' })}
          </Button>
          <Button onClick={onRegister} disabled={!canRegister || saving}>
            {intl.formatMessage({ id: 'camera.register' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
