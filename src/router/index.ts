import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      path: '/agent/:id',
      name: 'agent-chat',
      component: () => import('@/views/AgentChat.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/Settings.vue'),
    },
    {
      path: '/model-lab',
      name: 'model-lab',
      component: () => import('@/views/ModelLab.vue'),
    },
  ],
})

export default router
