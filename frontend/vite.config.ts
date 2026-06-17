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
    },
  },
  preview: { host: true, port: 3000 },
  build: { outDir: 'dist', sourcemap: false },
});
