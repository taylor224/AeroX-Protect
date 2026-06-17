import { Navigate } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';

export function RequirePermission({
  resource,
  action,
  children,
}: {
  resource: string;
  action: string;
  children: React.ReactNode;
}) {
  const { hasPermission } = useAuthContext();
  if (!hasPermission(resource, action)) return <Navigate to="/403" replace />;
  return <>{children}</>;
}
