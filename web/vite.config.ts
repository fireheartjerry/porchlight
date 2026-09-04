import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Porch. Dev server proxies /api to the FastAPI app (or dev/mock-api.mjs) on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE needs an unbuffered, long-lived connection.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            }
          })
        },
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
