import { createContext, useCallback, useContext, useRef, useState } from 'react';

import { ConfirmDialog } from '@/components/ConfirmDialog';

interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
}

const ConfirmContext = createContext<(opts: ConfirmOptions) => Promise<boolean>>(
  () => Promise.resolve(false),
);

/**
 * Imperative confirmation: `const confirm = useConfirm()` then
 * `if (await confirm({ title, description, destructive: true })) doIt()`.
 * One shared dialog lives at the app root, so any component can gate a destructive action
 * (delete / revoke / reset) behind a modal confirm without managing its own dialog state.
 */
export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);

  const confirm = useCallback(
    (o: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        resolver.current = resolve;
        setOpts(o);
      }),
    [],
  );

  const settle = (v: boolean) => {
    resolver.current?.(v);
    resolver.current = null;
    setOpts(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmDialog
        open={!!opts}
        onOpenChange={(v) => {
          if (!v) settle(false);
        }}
        onConfirm={() => settle(true)}
        title={opts?.title ?? ''}
        description={opts?.description}
        confirmLabel={opts?.confirmLabel}
        destructive={opts?.destructive}
      />
    </ConfirmContext.Provider>
  );
}
