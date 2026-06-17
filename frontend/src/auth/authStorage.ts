import { AUTH_STORAGE_KEY } from '@/config/env';

export interface AuthTokens {
  access_token: string;
  expires_in: number;
}

export function getAuth(): AuthTokens | undefined {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthTokens) : undefined;
  } catch {
    return undefined;
  }
}

export function setAuth(auth: AuthTokens): void {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

export function removeAuth(): void {
  try {
    localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function getAccessToken(): string | undefined {
  return getAuth()?.access_token;
}
