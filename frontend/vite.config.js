import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // `@/*` path alias required by shadcn/ui components (JS project).
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Listen on all interfaces so the app is reachable from a phone on the
    // same LAN (e.g. http://192.168.1.11:5173).
    host: true,
    port: 5173,
    // Proxy backend calls straight to the Python FastAPI layer.
    proxy: {
      '/sessions': {
        target: 'http://127.0.0.1:8999',
        changeOrigin: true,
      },
      '/scopes': {
        target: 'http://127.0.0.1:8999',
        changeOrigin: true,
      },
      '/agents': {
        target: 'http://127.0.0.1:8999',
        changeOrigin: true,
      },
      '/workdir': {
        target: 'http://127.0.0.1:8999',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8999',
        changeOrigin: true,
      },
    },
  },
})
