import { useState } from 'react';
import { useIntl } from 'react-intl';
import { useSearchParams } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';
import { ApiTokensTab } from '@/pages/automation/components/ApiTokensTab';
import { FlowsTab } from '@/pages/automation/components/FlowsTab';

type Tab = 'flows' | 'tokens';
const TABS: Tab[] = ['flows', 'tokens'];

export function AutomationPage() {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const [params] = useSearchParams();
  const initial = params.get('tab') as Tab | null;
  const [tab, setTab] = useState<Tab>(initial && TABS.includes(initial) ? initial : 'flows');

  const tabs: { key: Tab; show: boolean }[] = [
    { key: 'flows', show: hasPermission('rules', 'read') },
    { key: 'tokens', show: hasPermission('api_tokens', 'manage') },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{intl.formatMessage({ id: 'menu.rules' })}</h1>
        <div className="flex-1" />
        <div className="flex items-center gap-1 rounded border border-border p-0.5">
          {tabs.filter((t) => t.show).map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`rounded px-3 py-1 text-sm transition-colors ${tab === t.key ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary'}`}>
              {intl.formatMessage({ id: `auto.tab.${t.key}` })}
            </button>
          ))}
        </div>
      </div>

      {tab === 'flows' ? <FlowsTab /> : <ApiTokensTab />}
    </div>
  );
}
