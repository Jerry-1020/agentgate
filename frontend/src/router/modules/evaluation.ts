import type { RouteRecordRaw } from 'vue-router';
export const evaluationRoutes: RouteRecordRaw[] = [
  {
    path: '/welcome',
    name: 'welcome',
    component: () => import('../../views/evaluation/Welcome.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'evaluation',
    component: () => import('../../views/evaluation/index.vue'),
  },
];
