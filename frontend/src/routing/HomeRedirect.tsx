import { Navigate } from 'react-router-dom';

import { useAuthContext } from '@/auth/useAuthContext';
import { NAV_ITEMS } from '@/config/menu.config';

/** Home (`/`) → the first nav destination the user can actually access (live → cameras →
 * events → …). Avoids landing permission-limited users on a 403. */
export function HomeRedirect() {
  const { hasPermission } = useAuthContext();
  const target = NAV_ITEMS.find(
    (item) => item.path !== '/' && (!item.resource || hasPermission(item.resource, item.action ?? 'read')),
  );
  return <Navigate to={target?.path ?? '/cameras'} replace />;
}
