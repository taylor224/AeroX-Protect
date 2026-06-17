import { Check, Globe, LogOut, Menu } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useIntl } from 'react-intl';

import { useAuthContext } from '@/auth/useAuthContext';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { LANGUAGES, type Locale, useTranslation } from '@/i18n/TranslationProvider';

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  const intl = useIntl();
  const { currentUser, logout, setLanguage } = useAuthContext();
  const { locale, setLocale } = useTranslation();

  // Reflect the saved profile language once it loads (re-entry after re-login), without
  // clobbering a manual change the user makes during the session.
  const syncedFor = useRef<string | null>(null);
  useEffect(() => {
    const pref = currentUser?.language as Locale | undefined;
    if (pref && currentUser && syncedFor.current !== currentUser.uuid) {
      syncedFor.current = currentUser.uuid;
      if (pref !== locale) setLocale(pref);
    }
  }, [currentUser, locale, setLocale]);

  const chooseLanguage = async (next: Locale) => {
    if (next === locale) return;
    setLocale(next);
    try {
      await setLanguage(next);
    } catch {
      /* server sync is best-effort */
    }
  };

  const initial = (currentUser?.name || currentUser?.login_id || '?').charAt(0).toUpperCase();
  const currentLabel = LANGUAGES.find((l) => l.code === locale)?.label ?? locale;

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-2 border-b border-border bg-background px-4 md:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenuClick} aria-label="menu">
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex-1" />
      <div className="flex items-center gap-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
              <Globe className="h-4 w-4" />
              {currentLabel}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[9rem]">
            {LANGUAGES.map((l) => (
              <DropdownMenuItem key={l.code} onClick={() => void chooseLanguage(l.code)}>
                <Check className={`h-4 w-4 ${l.code === locale ? 'opacity-100' : 'opacity-0'}`} />
                {l.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 rounded-full p-0.5 outline-none transition-colors hover:bg-secondary">
              <Avatar>
                <AvatarFallback>{initial}</AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[12rem]">
            <DropdownMenuLabel className="px-2 py-1.5">
              <div className="text-sm font-medium text-foreground">{currentUser?.name}</div>
              <div className="text-xs text-muted-foreground">{currentUser?.login_id}</div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void logout()}>
              <LogOut className="h-4 w-4" />
              {intl.formatMessage({ id: 'auth.logout' })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
