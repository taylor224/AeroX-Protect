import { createContext, useCallback, useEffect, useMemo, useState } from 'react';

import { getAuth, removeAuth, setAuth } from '@/auth/authStorage';
import { hasPermission } from '@/auth/permissions';
import { api, setOnAuthCleared } from '@/lib/axios';
import type { ApiResponse, LoginResponse, MeResponse, MenuItem, PermissionMap, User } from '@/types/api';

interface AuthContextValue {
  loading: boolean;
  isAuthenticated: boolean;
  currentUser: User | null;
  permissions: PermissionMap;
  menus: MenuItem[];
  login: (loginId: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (resource: string, action: string) => boolean;
  setLanguage: (language: 'ko' | 'en') => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [permissions, setPermissions] = useState<PermissionMap>({});
  const [menus, setMenus] = useState<MenuItem[]>([]);

  const clearState = useCallback(() => {
    removeAuth();
    setCurrentUser(null);
    setPermissions({});
    setMenus([]);
  }, []);

  // Restore session on boot: if we hold a token, fetch /me (axios auto-refreshes if expired).
  const verify = useCallback(async () => {
    if (!getAuth()) {
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get<ApiResponse<MeResponse>>('/auth/me');
      if (data.data) {
        setCurrentUser(data.data.user);
        setPermissions(data.data.permissions);
        setMenus(data.data.menus);
      }
    } catch {
      clearState();
    } finally {
      setLoading(false);
    }
  }, [clearState]);

  useEffect(() => {
    setOnAuthCleared(clearState);
    void verify();
  }, [verify, clearState]);

  const login = useCallback(async (loginId: string, password: string) => {
    const { data } = await api.post<ApiResponse<LoginResponse>>('/auth/login', {
      login_id: loginId,
      password,
    });
    if (!data.data) throw new Error('invalid_response');
    setAuth({ access_token: data.data.access_token, expires_in: data.data.expires_in });
    // load full /me (menus + effective permissions)
    const me = await api.get<ApiResponse<MeResponse>>('/auth/me');
    if (me.data.data) {
      setCurrentUser(me.data.data.user);
      setPermissions(me.data.data.permissions);
      setMenus(me.data.data.menus);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* best effort */
    }
    clearState();
  }, [clearState]);

  const setLanguage = useCallback(
    async (language: 'ko' | 'en') => {
      await api.post('/auth/language', { language });
      setCurrentUser((prev) => (prev ? { ...prev, language } : prev));
    },
    [],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      loading,
      isAuthenticated: !!currentUser,
      currentUser,
      permissions,
      menus,
      login,
      logout,
      hasPermission: (resource, action) => hasPermission(permissions, resource, action),
      setLanguage,
    }),
    [loading, currentUser, permissions, menus, login, logout, setLanguage],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
