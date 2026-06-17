import { ShieldCheck } from 'lucide-react';
import { useIntl } from 'react-intl';
import { NavLink } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';
import { NAV_ITEMS } from '@/config/menu.config';
import { useFeatureFlags } from '@/lib/featureFlags';
import { cn } from '@/lib/utils';

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const intl = useIntl();
  const { hasPermission } = useAuthContext();
  const flags = useFeatureFlags();
  const items = NAV_ITEMS.filter(
    (item) =>
      (!item.resource || hasPermission(item.resource, item.action!)) &&
      (!item.flag || flags[item.flag]),
  );

  return (
    <aside className="flex h-full w-60 flex-col border-r border-border bg-background">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <ShieldCheck className="h-[18px] w-[18px]" strokeWidth={2} />
        </span>
        <span className="text-[15px] font-semibold tracking-tight text-foreground">AeroX Protect</span>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-axp ease-axp',
                isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className="h-[18px] w-[18px]" strokeWidth={isActive ? 2 : 1.75} />
                <span>{intl.formatMessage({ id: item.titleId })}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border px-5 py-3 text-[11px] text-muted-foreground">AeroX Protect · v5</div>
    </aside>
  );
}
