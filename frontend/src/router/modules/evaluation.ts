import type { RouteRecordRaw } from 'vue-router';
export const evaluationRoutes: RouteRecordRaw[] = [
  {
    path: '/:pathMatch(.*)*',
    name: 'evaluation',
    component: () => import('../../views/evaluation/index.vue'),
  },
];
