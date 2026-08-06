import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The backend (FastAPI) runs on :8000. We proxy API, media and WebSocket
// traffic through Vite in dev so the frontend can use same-origin paths.
const BACKEND = process.env.VITE_BACKEND || 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/media': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
})
