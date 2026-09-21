import { createRouter, createWebHashHistory } from 'vue-router';
import { evaluationRoutes } from './modules/evaluation';
import { constantRoutes } from './constant';
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [...constantRoutes, ...evaluationRoutes],
});
