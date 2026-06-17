import type { PermissionMap } from '@/types/api';

/** Wildcard-aware permission check, mirroring the server's PermissionService.has(). */
export function hasPermission(perms: PermissionMap | undefined, resource: string, action: string): boolean {
  if (!perms) return false;
  const star = perms['*'];
  if (star && (star.includes('*') || star.includes(action))) return true;
  const actions = perms[resource];
  return !!actions && (actions.includes('*') || actions.includes(action));
}
