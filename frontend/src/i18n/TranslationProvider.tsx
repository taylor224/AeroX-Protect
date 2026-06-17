import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { IntlProvider } from 'react-intl';

import { env } from '@/config/env';
import en from '@/i18n/messages/en.json';
import ko from '@/i18n/messages/ko.json';

export type Locale = 'ko' | 'en';

const messages: Record<Locale, Record<string, string>> = { ko, en };
const LANG_KEY = `${env.appName}-lang`;

/** Supported UI languages. Add a new one by dropping a messages file + an entry here
 * (and extending the Locale union). The selector + settings are driven by this list. */
export const LANGUAGES: { code: Locale; label: string }[] = [
  { code: 'ko', label: '한국어' },
  { code: 'en', label: 'English' },
];

interface TranslationContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

const TranslationContext = createContext<TranslationContextValue | null>(null);

export function TranslationProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    const stored = localStorage.getItem(LANG_KEY);
    return stored === 'en' || stored === 'ko' ? stored : 'ko';
  });

  const setLocale = (next: Locale) => {
    setLocaleState(next);
    localStorage.setItem(LANG_KEY, next);
  };

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale }), [locale]);

  return (
    <TranslationContext.Provider value={value}>
      <IntlProvider locale={locale} defaultLocale="ko" messages={messages[locale]}>
        {children}
      </IntlProvider>
    </TranslationContext.Provider>
  );
}

export function useTranslation() {
  const ctx = useContext(TranslationContext);
  if (!ctx) throw new Error('useTranslation must be used within <TranslationProvider>');
  return ctx;
}
