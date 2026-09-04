import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

import { AuthProvider } from '@/auth/AuthProvider';
import { ConfirmProvider } from '@/components/ConfirmProvider';
import { Toaster } from '@/components/ui/sonner';
import { TranslationProvider } from '@/i18n/TranslationProvider';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TranslationProvider>
          <ConfirmProvider>
            {/* v7_startTransition: lazy-route navigations keep the current page rendered
                until the chunk arrives instead of flashing the Suspense fallback */}
            <BrowserRouter future={{ v7_startTransition: true }}>{children}</BrowserRouter>
          </ConfirmProvider>
          <Toaster />
        </TranslationProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
