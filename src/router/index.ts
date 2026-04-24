import { createRouter, createWebHashHistory } from 'vue-router'
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
      path: '/agent/:id/profile',
      name: 'agent-profile',
      component: () => import('@/views/AgentProfile.vue'),
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
    // ── New top-level entries (issuse20 §1) ──
    {
      path: '/inbox',
      name: 'inbox',
      component: () => import('@/views/Inbox.vue'),
    },
    {
      path: '/team',
      name: 'team',
      component: () => import('@/views/Team.vue'),
    },
    {
      path: '/workflow',
      name: 'workflow',
      component: () => import('@/views/Workflow.vue'),
    },
    {
      path: '/assets',
      name: 'assets',
      component: () => import('@/views/Assets.vue'),
    },
    {
      path: '/admin/skills',
      name: 'admin-skills',
      // Admin-only marketplace review queue. Route-level guarding is
      // handled inside the component (checks auth store), because
      // the guard below only knows about login state; the component
      // can show a nicer "forbidden" UI for non-admin members.
      component: () => import('@/views/AdminSkillReview.vue'),
    },
    // ── Deep links (not in sidebar, reachable by URL) ──
    {
      path: '/pipeline/task/:id',
      name: 'pipeline-task',
      component: () => import('@/views/PipelineTaskDetail.vue'),
    },
    // ── Legacy routes (kept for backward compat, hidden from sidebar) ──
    {
      path: '/model-lab',
      name: 'model-lab',
      meta: { legacy: true },
      component: () => import('@/views/ModelLab.vue'),
    },
    {
      path: '/wayne-console',
      name: 'wayne-console',
      meta: { legacy: true },
      component: () => import('@/views/WayneConsole.vue'),
    },
    {
      path: '/wayne-stack',
      name: 'wayne-stack',
      meta: { legacy: true },
      component: () => import('@/views/WayneStack.vue'),
    },
    {
      path: '/pipeline',
      name: 'pipeline',
      meta: { legacy: true },
      component: () => import('@/views/PipelineDashboard.vue'),
    },
    {
      path: '/workflow-builder',
      name: 'workflow-builder',
      meta: { legacy: true },
      component: () => import('@/views/WorkflowBuilder.vue'),
    },
    {
      path: '/skills',
      name: 'skills',
      meta: { legacy: true },
      component: () => import('@/views/SkillsView.vue'),
    },
    {
      path: '/agents-console',
      name: 'agents-console',
      meta: { legacy: true },
      component: () => import('@/views/AgentsConsole.vue'),
    },
    {
      path: '/mcp-servers',
      name: 'mcp-servers',
      meta: { legacy: true },
      component: () => import('@/views/McpServers.vue'),
    },
    {
      path: '/eval-lab',
      name: 'eval-lab',
      meta: { legacy: true },
      component: () => import('@/views/EvalLab.vue'),
    },
    {
      path: '/plan-inbox',
      name: 'plan-inbox',
      meta: { legacy: true },
      component: () => import('@/views/PlanInbox.vue'),
    },
    {
      path: '/codebase-lab',
      name: 'codebase-lab',
      meta: { legacy: true },
      component: () => import('@/views/CodebaseLab.vue'),
    },
    {
      path: '/insights/digest',
      name: 'insights-digest',
      meta: { legacy: true },
      component: () => import('@/views/InsightsDigest.vue'),
    },
    {
      path: '/insights/observability',
      name: 'insights-observability',
      meta: { legacy: true },
      component: () => import('@/views/InsightsObservability.vue'),
    },
    {
      path: '/share/:token',
      name: 'share',
      meta: { public: true },
      component: () => import('@/views/SharePage.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      meta: { public: true },
      component: () => import('@/views/NotFound.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
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
