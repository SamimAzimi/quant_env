import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies /api to the FastAPI backend so both run side by side.
export default defineConfig({
  plugins: [react()],
  define: {
    // Shown in the header so a stale dist/ is immediately recognizable.
    __BUILD_TIME__: JSON.stringify(new Date().toISOString().slice(0, 16).replace('T', ' ')),
  },
  server: {
    host: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
