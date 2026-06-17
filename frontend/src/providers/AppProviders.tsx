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
            <BrowserRouter>{children}</BrowserRouter>
          </ConfirmProvider>
          <Toaster />
        </TranslationProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
