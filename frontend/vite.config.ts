import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: false },
      // A new deploy replaces the old cached app on the next visit instead of waiting for every tab to close.
      workbox: { cleanupOutdatedCaches: true, clientsClaim: true, skipWaiting: true, navigateFallbackDenylist: [/^\/api\//, /^\/uploads\//, /^\/fixtures\//] },
      manifest: {
        name: 'NadiSaathi',
        short_name: 'NadiSaathi',
        description: 'Flood early warning and relief for Nepal and India',
        theme_color: '#121211',
        background_color: '#f3f2ee',
        display: 'standalone',
        start_url: '/',
        icons: [],
      },
    }),
  ],
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
});
