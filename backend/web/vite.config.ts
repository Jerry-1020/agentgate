import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.AGENTGATE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    allowedHosts: ['mscli.dev'],
    proxy: { '/api': apiTarget, '/health': apiTarget },
  },
})
