export const env = {
  apiUrl: import.meta.env.VITE_APP_API_URL ?? '/api/v1',
  appName: import.meta.env.VITE_APP_NAME ?? 'axp',
  appVersion: import.meta.env.VITE_APP_VERSION ?? '1',
};

export const AUTH_STORAGE_KEY = `${env.appName}-auth-v${env.appVersion}`;
