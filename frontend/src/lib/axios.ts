import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { toast } from 'sonner';

import { getAccessToken, removeAuth, setAuth } from '@/auth/authStorage';
import { env } from '@/config/env';
import type { ApiResponse, LoginResponse } from '@/types/api';

export const api = axios.create({
  baseURL: env.apiUrl,
  withCredentials: true, // send the httpOnly refresh cookie
});

// Attach the in-memory/localStorage access token.
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

// Single-flight refresh: concurrent 401s share one refresh round-trip.
let refreshPromise: Promise<string | null> | null = null;
let onAuthCleared: (() => void) | null = null;

export function setOnAuthCleared(cb: () => void) {
  onAuthCleared = cb;
}

async function runRefresh(): Promise<string | null> {
  try {
    // Bare axios (no interceptors) to avoid recursion. Refresh token is the cookie.
    const res = await axios.post<ApiResponse<LoginResponse>>(
      `${env.apiUrl}/auth/refresh`,
      {},
      { withCredentials: true },
    );
    const data = res.data?.data;
    if (data?.access_token) {
      setAuth({ access_token: data.access_token, expires_in: data.expires_in });
      return data.access_token;
    }
    return null;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    const status = error.response?.status;
    const url = original?.url ?? '';
    const isAuthCall = url.includes('/auth/refresh') || url.includes('/auth/login');

    if (status === 401 && original && !original._retry && !isAuthCall) {
      original._retry = true;
      if (!refreshPromise) {
        refreshPromise = runRefresh().finally(() => {
          refreshPromise = null;
        });
      }
      const newToken = await refreshPromise;
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      }
      // refresh failed → clear session and bounce to login
      removeAuth();
      onAuthCleared?.();
      if (!window.location.pathname.startsWith('/auth')) {
        window.location.href = '/auth/login';
      }
    }

    // 403 = authenticated but lacks permission → inform, stay on page (PLAN §8.6)
    if (status === 403) {
      toast.error('권한이 없습니다.');
    }

    return Promise.reject(error);
  },
);
