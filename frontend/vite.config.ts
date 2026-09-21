import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8098';
  const port = Number(env.FRONTEND_PORT || 5198);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('FRONTEND_PORT must be an integer between 1 and 65535');
  }
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      host: '127.0.0.1',
      port,
      strictPort: true,
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
        ...(env.AGENT_PLATFORM_PROXY_TARGET
          ? {
              '/web': { target: env.AGENT_PLATFORM_PROXY_TARGET, changeOrigin: true },
            }
          : {}),
        '/race-api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/race-api/, '/api'),
        },
      },
    },
  };
});
