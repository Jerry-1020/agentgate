import { createRouter, createWebHashHistory } from 'vue-router';
import { evaluationRoutes } from './modules/evaluation';
import { constantRoutes } from './constant';
import { useAuthStore } from '../stores/modules/auth';
import { embeddedMode } from '../integration/platform-url-context';

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [...constantRoutes, ...evaluationRoutes],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (embeddedMode) {
    // App.vue prevents business components from mounting without identity.
    if (to.path === '/welcome') return '/overview';
    return true;
  }
  if (to.path === '/welcome') return auth.authenticated ? '/overview' : true;
  return auth.authenticated ? true : '/welcome';
});
