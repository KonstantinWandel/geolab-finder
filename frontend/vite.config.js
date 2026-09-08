import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// The build id goes into every bundle name. Why that matters here: on 2026-09-05 a missing bundle
// was answered with index.html AND the header "immutable, max-age=1y", so browsers stored an HTML
// document under a bundle address, permanently, and the app rendered a white screen on every visit.
// The server side is fixed (Caddy now tests that the file exists before promising immutability, and
// a missing asset answers 404), but a browser that already holds such an entry keeps it for a year:
// the address never changes, because Vite derives it from the content alone. A build id in the name
// gives every deployment fresh addresses, so a poisoned entry is simply never asked for again.
// Long-lived caching still works: each address remains immutable, only a new build creates new ones.
const bau = process.env.VITE_BUILD_ID || 'dev'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        entryFileNames: `assets/[name]-${bau}-[hash].js`,
        chunkFileNames: `assets/[name]-${bau}-[hash].js`,
        assetFileNames: `assets/[name]-${bau}-[hash].[ext]`,
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
