import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vite';

// Dev server proxies /api to the backend (uWSGI :10000). In production the frontend
// container's nginx proxies /api to axp-backend:10000.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: true,
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:10000', changeOrigin: true },
      // MSE live WS (nginx/Caddy proxies this to go2rtc after ticket auth in prod)
      '/live-ws': {
        target: 'http://localhost:1984',
        ws: true,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/live-ws\/?/, '/api/ws'),
      },
      // native-install launcher control API (update progress polling)
      '/updater': {
        target: 'http://localhost:10099',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/updater/, ''),
      },
    },
  },
  preview: { host: true, port: 3000 },
  build: { outDir: 'dist', sourcemap: false },
});
