import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { getAiSettings, updateAiSettings } from '@/pages/ai/ai.api';
import { YOLO_MODELS, type AiSettings } from '@/types/p4';

export function AiSettingsPanel({ canEdit }: { canEdit: boolean }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Partial<AiSettings>>({});

  const settingsQuery = useQuery({ queryKey: ['ai-settings'], queryFn: () => getAiSettings() });
  useEffect(() => {
    if (settingsQuery.data?.global) setForm(settingsQuery.data.global);
  }, [settingsQuery.data]);

  const saveMut = useMutation({
    mutationFn: (body: Partial<AiSettings>) => updateAiSettings(body),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'ai.settings_saved' }));
      void queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const g = settingsQuery.data?.global;
  const set = (patch: Partial<AiSettings>) => setForm((f) => ({ ...f, ...patch }));

  return (
    <Card className="max-w-2xl space-y-5 bg-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <Label className="text-base">{intl.formatMessage({ id: 'ai.gpu_toggle' })}</Label>
          <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'ai.gpu_hint' })}</p>
        </div>
        <Switch checked={!!form.gpu_enabled} disabled={!canEdit} onCheckedChange={(v) => set({ gpu_enabled: v })} />
      </div>

      <div className="flex items-center justify-between border-t border-border pt-4">
        <div>
          <Label className="text-base">{intl.formatMessage({ id: 'ai.hwaccel' })}</Label>
          <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'ai.hwaccel_hint' })}</p>
        </div>
        <select
          className="h-9 rounded border border-input bg-background px-2 text-sm"
          value={form.hwaccel ?? 'none'}
          disabled={!canEdit}
          onChange={(e) => set({ hwaccel: e.target.value })}
        >
          {['none', 'auto', 'cuda', 'vaapi', 'qsv', 'videotoolbox'].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>{intl.formatMessage({ id: 'ai.model' })}</Label>
          <select
            className="h-10 w-full rounded border border-input bg-background px-2 text-sm"
            value={form.model ?? 'yolo11n'}
            disabled={!canEdit}
            onChange={(e) => set({ model: e.target.value })}
          >
            {YOLO_MODELS.map((m) => (
              <option key={m} value={m}>{m.startsWith('yolo11') ? `${m} (latest)` : m}</option>
            ))}
          </select>
        </div>
        <Slider label={intl.formatMessage({ id: 'ai.target_fps' })} min={1} max={15} value={form.target_fps ?? 5}
          disabled={!canEdit} onChange={(v) => set({ target_fps: v })} />
        <Slider label="imgsz" min={320} max={1280} step={160} value={form.imgsz ?? 640}
          disabled={!canEdit} onChange={(v) => set({ imgsz: v })} />
        <Slider label={intl.formatMessage({ id: 'ai.min_conf' })} min={0} max={100} value={form.min_confidence ?? 35}
          disabled={!canEdit} onChange={(v) => set({ min_confidence: v })} />
      </div>

      <div className="flex flex-wrap gap-5">
        <Toggle label={intl.formatMessage({ id: 'ai.clip_verify' })} checked={!!form.clip_enabled} disabled={!canEdit}
          onChange={(v) => set({ clip_enabled: v })} />
        <Toggle label={intl.formatMessage({ id: 'ai.live_overlay' })} checked={!!form.live_overlay_enabled} disabled={!canEdit}
          onChange={(v) => set({ live_overlay_enabled: v })} />
        <Toggle label={intl.formatMessage({ id: 'ai.store_crops' })} checked={!!form.store_crops} disabled={!canEdit}
          onChange={(v) => set({ store_crops: v })} />
      </div>

      <div className="space-y-3 rounded border border-border p-3">
        <Toggle label={intl.formatMessage({ id: 'ai.audio_enabled' })} checked={!!form.audio_enabled} disabled={!canEdit}
          onChange={(v) => set({ audio_enabled: v })} />
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'ai.audio_hint' })}</p>
        <Slider label={intl.formatMessage({ id: 'ai.audio_threshold' })} min={0} max={100} value={form.audio_threshold ?? 60}
          disabled={!canEdit} onChange={(v) => set({ audio_threshold: v })} />
      </div>

      {g && (
        <p className="text-xs text-muted-foreground">
          {intl.formatMessage({ id: 'ai.gpu_status' }, { state: g.gpu_enabled ? 'GPU' : 'CPU' })}
        </p>
      )}
      {canEdit && (
        <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate(form)}>
          {intl.formatMessage({ id: 'common.save' })}
        </Button>
      )}
    </Card>
  );
}

function Slider({ label, value, min, max, step = 1, disabled, onChange }:
  { label: string; value: number; min: number; max: number; step?: number; disabled?: boolean; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1.5">
      <Label>{label} <span className="tabular-nums text-muted-foreground">· {value}</span></Label>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))} className="w-full" />
    </div>
  );
}

function Toggle({ label, checked, disabled, onChange }:
  { label: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
      {label}
    </label>
  );
}
