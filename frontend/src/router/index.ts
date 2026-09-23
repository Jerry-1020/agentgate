import { createRouter, createWebHashHistory } from 'vue-router';
import { evaluationRoutes } from './modules/evaluation';
import { constantRoutes } from './constant';
import { useAuthStore } from '../stores/modules/auth';
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [...constantRoutes, ...evaluationRoutes],
});
router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.path === '/welcome') return auth.authenticated ? '/overview' : true;
  return auth.authenticated ? true : '/welcome';
});
