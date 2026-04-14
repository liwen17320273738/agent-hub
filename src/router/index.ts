import { createRouter, createWebHashHistory } from 'vue-router'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      meta: { public: true },
      component: () => import('@/views/Login.vue'),
    },
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
    {
      path: '/wayne-console',
      name: 'wayne-console',
      component: () => import('@/views/WayneConsole.vue'),
    },
    {
      path: '/wayne-stack',
      name: 'wayne-stack',
      component: () => import('@/views/WayneStack.vue'),
    },
    {
      path: '/pipeline',
      name: 'pipeline',
      component: () => import('@/views/PipelineDashboard.vue'),
    },
    {
      path: '/pipeline/task/:id',
      name: 'pipeline-task',
      component: () => import('@/views/PipelineTaskDetail.vue'),
    },
    {
      path: '/skills',
      name: 'skills',
      component: () => import('@/views/SkillsView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  if (!isEnterpriseBuild) return true
  const auth = useAuthStore()
  if (!auth.initialized) await auth.hydrate()
  if (to.meta.public) {
    if (to.name === 'login' && auth.isLoggedIn) return { path: '/' }
    return true
  }
  if (!auth.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  return true
})

export default router
