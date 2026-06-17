import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';
import { ScreenLoader } from '@/components/ScreenLoader';

export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuthContext();
  const location = useLocation();

  if (loading) return <ScreenLoader />;
  if (!isAuthenticated) return <Navigate to="/auth/login" replace state={{ from: location }} />;
  return <Outlet />;
}
