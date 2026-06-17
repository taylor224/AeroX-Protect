import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { useAuthContext } from '@/auth/useAuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { LANGUAGES } from '@/i18n/TranslationProvider';
import { getFeatureFlags, setFeatureFlag, useFeatureFlag } from '@/lib/featureFlags';
import { getPortalConfig, updatePortalConfig, type PortalConfig } from '@/pages/live/portal.api';
import { getMapConfig, updateMapConfig, type MapProvider } from '@/pages/maps/map.api';
import {
  COMMON_TIMEZONES,
  getGeneralSettings,
  getTwilioConfig,
  updateGeneralSettings,
  updateTwilioConfig,
  type TwilioUpdate,
} from '@/pages/settings.api';

export function SettingsPage() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canManage = hasPermission('settings', 'update');

  const settingsQuery = useQuery({ queryKey: ['general-settings'], queryFn: getGeneralSettings });
  const [tz, setTz] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [webrtcIp, setWebrtcIp] = useState('');
  useEffect(() => {
    if (settingsQuery.data) {
      setTz(settingsQuery.data.timezone);
      setBaseUrl(settingsQuery.data.public_base_url ?? '');
      setWebrtcIp(settingsQuery.data.webrtc_candidate_ip ?? '');
    }
  }, [settingsQuery.data]);

  const saveLang = useMutation({
    mutationFn: (lang: 'ko' | 'en') => updateGeneralSettings({ default_language: lang }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'settings.lang_saved' }));
      void queryClient.invalidateQueries({ queryKey: ['general-settings'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  // browser's own zone first, then the common list (deduped)
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = Array.from(new Set([browserTz, ...COMMON_TIMEZONES, tz].filter(Boolean)));

  const saveTz = useMutation({
    mutationFn: () => updateGeneralSettings({ timezone: tz }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'settings.tz_saved' }));
      void queryClient.invalidateQueries({ queryKey: ['general-settings'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const saveBaseUrl = useMutation({
    mutationFn: () => updateGeneralSettings({ public_base_url: baseUrl.trim() }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'settings.base_url_saved' }));
      void queryClient.invalidateQueries({ queryKey: ['general-settings'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'settings.base_url_invalid' })),
  });

  const saveWebrtcIp = useMutation({
    mutationFn: () => updateGeneralSettings({ webrtc_candidate_ip: webrtcIp.trim() }),
    onSuccess: () => {
      toast.success(intl.formatMessage({ id: 'settings.webrtc_ip_saved' }));
      void queryClient.invalidateQueries({ queryKey: ['general-settings'] });
    },
    onError: () => toast.error(intl.formatMessage({ id: 'settings.webrtc_ip_invalid' })),
  });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{intl.formatMessage({ id: 'settings.title' })}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: 'settings.timezone' })}
              </div>
              <div className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'settings.timezone.desc' })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <select
                className="h-9 w-56 rounded border border-input bg-background px-2 text-sm"
                value={tz}
                disabled={!canManage}
                onChange={(e) => setTz(e.target.value)}
              >
                {zones.map((z) => (
                  <option key={z} value={z}>{z}</option>
                ))}
              </select>
              {canManage && (
                <Button size="sm" disabled={saveTz.isPending || !tz || tz === settingsQuery.data?.timezone}
                  onClick={() => saveTz.mutate()}>
                  {intl.formatMessage({ id: 'common.save' })}
                </Button>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: 'settings.default_language' })}
              </div>
              <div className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'settings.default_language.desc' })}
              </div>
            </div>
            <select
              className="h-9 w-56 rounded border border-input bg-background px-2 text-sm"
              value={settingsQuery.data?.default_language ?? 'ko'}
              disabled={!canManage || saveLang.isPending}
              onChange={(e) => saveLang.mutate(e.target.value as 'ko' | 'en')}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: 'settings.base_url' })}
              </div>
              <div className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'settings.base_url.desc' })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                className="h-9 w-72"
                placeholder={window.location.origin}
                value={baseUrl}
                disabled={!canManage}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              {canManage && (
                <Button size="sm"
                  disabled={saveBaseUrl.isPending || baseUrl.trim() === (settingsQuery.data?.public_base_url ?? '')}
                  onClick={() => saveBaseUrl.mutate()}>
                  {intl.formatMessage({ id: 'common.save' })}
                </Button>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: 'settings.webrtc_ip' })}
              </div>
              <div className="text-xs text-muted-foreground">
                {intl.formatMessage({ id: 'settings.webrtc_ip.desc' })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                className="h-9 w-72"
                placeholder="192.168.1.10"
                value={webrtcIp}
                disabled={!canManage}
                onChange={(e) => setWebrtcIp(e.target.value)}
              />
              {canManage && (
                <Button size="sm"
                  disabled={saveWebrtcIp.isPending || webrtcIp.trim() === (settingsQuery.data?.webrtc_candidate_ip ?? '')}
                  onClick={() => saveWebrtcIp.mutate()}>
                  {intl.formatMessage({ id: 'common.save' })}
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <MapConfigCard />
      <TwilioConfigCard />
      <FeatureFlagsCard />
      <PortalConfigCard />
    </div>
  );
}

function MapConfigCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const enabled = useFeatureFlag('maps');
  const canManage = hasPermission('maps', 'update');
  const [provider, setProvider] = useState<MapProvider | ''>('');
  const [key, setKey] = useState('');

  const cfgQuery = useQuery({ queryKey: ['map-config'], queryFn: getMapConfig, enabled });
  const cfg = cfgQuery.data;
  const curProvider = (provider || cfg?.provider || 'osm') as MapProvider;

  const saveMut = useMutation({
    mutationFn: (body: { provider?: MapProvider; google_api_key?: string }) => updateMapConfig(body),
    onSuccess: () => {
      setKey('');
      setProvider('');
      void queryClient.invalidateQueries({ queryKey: ['map-config'] });
      void queryClient.invalidateQueries({ queryKey: ['google-tile-session'] });
      toast.success(intl.formatMessage({ id: 'map.cfg_saved' }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  if (!enabled) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'map.cfg_title' })}</CardTitle>
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'map.cfg_desc' })}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-4">
          <span className="text-sm font-medium">{intl.formatMessage({ id: 'map.cfg_provider' })}</span>
          <select
            className="h-9 w-56 rounded border border-input bg-background px-2 text-sm"
            value={curProvider}
            disabled={!canManage}
            onChange={(e) => setProvider(e.target.value as MapProvider)}
          >
            <option value="osm">{intl.formatMessage({ id: 'map.cfg_osm' })}</option>
            <option value="google">{intl.formatMessage({ id: 'map.cfg_google' })}</option>
          </select>
        </div>

        {curProvider === 'google' && (
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'map.cfg_key' })}</span>
            <Input
              type="password"
              disabled={!canManage}
              placeholder={cfg?.has_key
                ? intl.formatMessage({ id: 'map.cfg_key_set' })
                : intl.formatMessage({ id: 'map.cfg_key_ph' })}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <span className="text-[11px] text-muted-foreground">{intl.formatMessage({ id: 'map.cfg_key_hint' })}</span>
          </label>
        )}

        {canManage && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={saveMut.isPending}
              onClick={() =>
                saveMut.mutate({
                  provider: curProvider,
                  ...(curProvider === 'google' && key ? { google_api_key: key } : {}),
                })
              }
            >
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
            {cfg?.has_key && (
              <Button size="sm" variant="ghost" disabled={saveMut.isPending}
                onClick={() => saveMut.mutate({ provider: curProvider, google_api_key: '' })}>
                {intl.formatMessage({ id: 'map.cfg_key_clear' })}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TwilioConfigCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canManage = hasPermission('settings', 'update');
  const [form, setForm] = useState<TwilioUpdate>({});

  const cfgQuery = useQuery({ queryKey: ['twilio-config'], queryFn: getTwilioConfig });
  const cfg = cfgQuery.data;

  const saveMut = useMutation({
    mutationFn: (body: TwilioUpdate) => updateTwilioConfig(body),
    onSuccess: () => {
      setForm({});
      void queryClient.invalidateQueries({ queryKey: ['twilio-config'] });
      toast.success(intl.formatMessage({ id: 'twilio.saved' }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const sid = form.account_sid ?? cfg?.account_sid ?? '';
  const from = form.from_number ?? cfg?.from_number ?? '';

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'twilio.title' })}</CardTitle>
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'twilio.desc' })}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-xs">
          <span className={`inline-block h-2 w-2 rounded-full ${cfg?.configured ? 'bg-emerald-500' : 'bg-muted-foreground/40'}`} />
          <span className="text-muted-foreground">
            {intl.formatMessage({ id: cfg?.configured ? 'twilio.status_on' : 'twilio.status_off' })}
          </span>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'twilio.sid' })}</span>
            <Input placeholder="ACxxxxxxxx" value={sid} disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, account_sid: e.target.value }))} />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'twilio.from' })}</span>
            <Input placeholder="+15550001111" value={from} disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, from_number: e.target.value }))} />
          </label>
        </div>
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'twilio.token' })}</span>
          <Input type="password" disabled={!canManage}
            placeholder={cfg?.has_token
              ? intl.formatMessage({ id: 'twilio.token_set' })
              : intl.formatMessage({ id: 'twilio.token_ph' })}
            value={form.auth_token ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, auth_token: e.target.value }))} />
        </label>
        {canManage && (
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={saveMut.isPending || Object.keys(form).length === 0}
              onClick={() => saveMut.mutate(form)}>
              {intl.formatMessage({ id: 'common.save' })}
            </Button>
            {cfg?.has_token && (
              <Button size="sm" variant="ghost" disabled={saveMut.isPending}
                onClick={() => saveMut.mutate({ auth_token: '' })}>
                {intl.formatMessage({ id: 'twilio.clear' })}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PortalConfigCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canManage = hasPermission('portal', 'manage');
  const [form, setForm] = useState<Partial<PortalConfig> & { auth_secret?: string }>({});

  const cfgQuery = useQuery({
    queryKey: ['portal-config'],
    queryFn: getPortalConfig,
    enabled: canManage,
  });
  const cfg = cfgQuery.data;
  const val = <K extends keyof PortalConfig>(k: K): PortalConfig[K] | undefined =>
    (form[k] ?? cfg?.[k]) as PortalConfig[K] | undefined;

  const saveMut = useMutation({
    mutationFn: () => updatePortalConfig(form),
    onSuccess: () => {
      setForm({});
      void queryClient.invalidateQueries({ queryKey: ['portal-config'] });
      toast.success(intl.formatMessage({ id: 'portal.saved' }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  if (!canManage) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'portal.title' })}</CardTitle>
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'portal.desc' })}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{intl.formatMessage({ id: 'portal.enabled' })}</span>
          <Switch checked={!!val('enabled')} onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Input placeholder="turn.example.com" value={val('turn_host') ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, turn_host: e.target.value }))} />
          <Input type="number" placeholder="3478" value={val('turn_port') ?? 3478}
            onChange={(e) => setForm((f) => ({ ...f, turn_port: Number(e.target.value) }))} />
          <select className="h-9 rounded border border-input bg-background px-2 text-sm" value={val('turn_protocol') ?? 'udp'}
            onChange={(e) => setForm((f) => ({ ...f, turn_protocol: e.target.value as 'udp' | 'tcp' }))}>
            <option value="udp">UDP</option>
            <option value="tcp">TCP</option>
          </select>
          <Input type="number" placeholder="3600" value={val('ttl_seconds') ?? 3600}
            onChange={(e) => setForm((f) => ({ ...f, ttl_seconds: Number(e.target.value) }))} />
        </div>
        <Input type="password"
          placeholder={cfg?.has_secret
            ? intl.formatMessage({ id: 'portal.secret_set' })
            : intl.formatMessage({ id: 'portal.secret_ph' })}
          value={form.auth_secret ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, auth_secret: e.target.value }))} />
        <Button size="sm" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
          {intl.formatMessage({ id: 'common.save' })}
        </Button>
      </CardContent>
    </Card>
  );
}

function FeatureFlagsCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuthContext();
  const canManage = hasPermission('feature_flags', 'manage');

  const flagsQuery = useQuery({ queryKey: ['feature-flags'], queryFn: getFeatureFlags });

  const toggleMut = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) => setFeatureFlag(key, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['feature-flags'] });
      toast.success(intl.formatMessage({ id: 'settings.flags.saved' }));
    },
    onError: () => toast.error(intl.formatMessage({ id: 'common.error' })),
  });

  const flags = flagsQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{intl.formatMessage({ id: 'settings.flags' })}</CardTitle>
        <p className="text-xs text-muted-foreground">{intl.formatMessage({ id: 'settings.flags.desc' })}</p>
      </CardHeader>
      <CardContent className="space-y-1">
        {flags.map((f, i) => (
          <div
            key={f.key}
            className={`flex items-center justify-between gap-4 py-3 ${i > 0 ? 'border-t border-border' : ''}`}
          >
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground">
                {intl.formatMessage({ id: `flag.${f.key}`, defaultMessage: f.key.replace(/_/g, ' ') })}
              </div>
              <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {intl.formatMessage({ id: `flag.${f.key}.desc`, defaultMessage: f.description ?? '' })}
              </div>
            </div>
            <Switch
              checked={f.enabled}
              disabled={!canManage || toggleMut.isPending}
              onCheckedChange={(enabled) => toggleMut.mutate({ key: f.key, enabled })}
            />
          </div>
        ))}
        {flags.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {intl.formatMessage({ id: 'common.loading' })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
