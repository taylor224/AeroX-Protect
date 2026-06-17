import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { Card } from '@/components/ui/card';
import { useFeatureFlag } from '@/lib/featureFlags';
import { listCameras } from '@/pages/cameras/camera.api';
import { AiNodes } from '@/pages/ai/components/AiNodes';
import { AiSettingsPanel } from '@/pages/ai/components/AiSettingsPanel';
import { AudioDetections } from '@/pages/ai/components/AudioDetections';
import { CountingEditor } from '@/pages/ai/components/CountingEditor';
import { ObjectSearch } from '@/pages/ai/components/ObjectSearch';
import { ObjectTriggers } from '@/pages/ai/components/ObjectTriggers';
import { ZoneEditor } from '@/pages/ai/components/ZoneEditor';

type Tab = 'search' | 'zones' | 'triggers' | 'counting' | 'audio' | 'settings' | 'nodes';

export function AiPage() {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const countingEnabled = useFeatureFlag('object_counting') || useFeatureFlag('loitering');
  const audioEnabled = useFeatureFlag('audio_detection');
  const [tab, setTab] = useState<Tab>('search');
  const [cameraUuid, setCameraUuid] = useState('');

  const camerasQuery = useQuery({ queryKey: ['cameras'], queryFn: () => listCameras() });
  const cameras = camerasQuery.data?.items ?? [];
  const selectedUuid = cameraUuid || cameras[0]?.uuid || '';
  const selectedCamera = cameras.find((c) => c.uuid === selectedUuid);

  const tabs: { key: Tab; show: boolean; cam: boolean }[] = [
    { key: 'search', show: hasPermission('detections', 'read'), cam: true },
    { key: 'zones', show: hasPermission('zones', 'read'), cam: true },
    { key: 'triggers', show: hasPermission('triggers', 'read'), cam: true },
    { key: 'counting', show: hasPermission('ai', 'count') && countingEnabled, cam: true },
    { key: 'audio', show: hasPermission('ai', 'audio') && audioEnabled, cam: true },
    { key: 'settings', show: hasPermission('ai', 'read'), cam: false },
    { key: 'nodes', show: hasPermission('ai_nodes', 'manage'), cam: false },
  ];
  const active = tabs.find((t) => t.key === tab);
  const needsCamera = active?.cam ?? false;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.ai' })}</h1>
        {needsCamera && (
          <select
            className="h-9 rounded border border-input bg-background px-2 text-sm"
            value={selectedUuid}
            onChange={(e) => setCameraUuid(e.target.value)}
          >
            {cameras.map((c) => (
              <option key={c.uuid} value={c.uuid}>{c.name}</option>
            ))}
          </select>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-1 rounded border border-border p-0.5">
          {tabs.filter((t) => t.show).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                tab === t.key ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'
              }`}
            >
              {intl.formatMessage({ id: `ai.tab.${t.key}` })}
            </button>
          ))}
        </div>
      </div>

      {needsCamera && !selectedUuid ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {intl.formatMessage({ id: 'camera.empty' })}
        </Card>
      ) : tab === 'search' ? (
        <ObjectSearch cameraUuid={selectedUuid} cameraId={selectedCamera?.id} />
      ) : tab === 'zones' ? (
        <ZoneEditor cameraUuid={selectedUuid} canEdit={hasPermission('zones', 'update')} />
      ) : tab === 'triggers' ? (
        <ObjectTriggers cameraUuid={selectedUuid} cameraName={selectedCamera?.name ?? ''} canEdit={hasPermission('triggers', 'update')} />
      ) : tab === 'counting' ? (
        <CountingEditor cameraUuid={selectedUuid} canEdit={hasPermission('ai', 'count')} />
      ) : tab === 'audio' ? (
        <AudioDetections cameraUuid={selectedUuid} />
      ) : tab === 'settings' ? (
        <AiSettingsPanel canEdit={hasPermission('ai', 'update')} />
      ) : (
        <AiNodes />
      )}
    </div>
  );
}
