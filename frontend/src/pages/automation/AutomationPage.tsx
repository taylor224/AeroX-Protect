import { useState } from 'react';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { ApiTokensTab } from '@/pages/automation/components/ApiTokensTab';
import { NotificationsTab } from '@/pages/automation/components/NotificationsTab';
import { RulesTab } from '@/pages/automation/components/RulesTab';

type Tab = 'rules' | 'notifications' | 'tokens';

export function AutomationPage() {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const [tab, setTab] = useState<Tab>('rules');

  const tabs: { key: Tab; show: boolean }[] = [
    { key: 'rules', show: hasPermission('rules', 'read') },
    { key: 'notifications', show: hasPermission('notifications', 'read') },
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

      {tab === 'rules' ? <RulesTab /> : tab === 'notifications' ? <NotificationsTab /> : <ApiTokensTab />}
    </div>
  );
}
