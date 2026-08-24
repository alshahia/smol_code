import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config for the smolcode web SPA (M8, decision 0010 D3).
// In dev mode, the user runs `smolcode web` (FastAPI on 127.0.0.1:7860)
// separately, and `pnpm dev` (Vite on 5173). Vite proxies /api/* to
// the FastAPI server so the SPA can call same-origin URLs in dev.
// In production, `pnpm build` outputs to web/dist/, which the
// FastAPI server serves as static files.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:7860',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
