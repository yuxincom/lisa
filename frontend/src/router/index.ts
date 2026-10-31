import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/layouts/AppLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/dashboard' },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/pages/DashboardPage.vue'),
        meta: { title: '指挥驾驶舱', permission: 'dashboard:read' },
      },
      {
        path: 'gantt',
        name: 'gantt',
        component: () => import('@/pages/GanttPage.vue'),
        meta: { title: '智能排产', permission: 'plans:read' },
      },
      {
        path: 'plans',
        name: 'plans',
        component: () => import('@/pages/PlansPage.vue'),
        meta: { title: '方案审批', permission: 'plans:read' },
      },
      {
        path: 'agents',
        name: 'agents',
        component: () => import('@/pages/AgentsPage.vue'),
        meta: { title: '智能体中心', permission: 'agents:read' },
      },
      {
        path: 'changes',
        name: 'changes',
        component: () => import('@/pages/ChangesPage.vue'),
        meta: { title: '变更影响', permission: 'changes:read' },
      },
      {
        path: 'kits',
        name: 'kits',
        component: () => import('@/pages/KitsPage.vue'),
        meta: { title: '齐套检查', permission: 'kits:read' },
      },
      {
        path: 'orders',
        name: 'orders',
        component: () => import('@/pages/OrdersPage.vue'),
        meta: { title: '订单台账', permission: 'plans:read' },
      },
      {
        path: 'data',
        name: 'data',
        component: () => import('@/pages/DataPage.vue'),
        meta: { title: '数据基座', permission: 'data:read' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/pages/KnowledgePage.vue'),
        meta: { title: '知识规则', permission: 'knowledge:read' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/pages/AuditPage.vue'),
        meta: { title: '审计追溯', permission: 'audit:read' },
      },
      {
        path: 'alerts',
        name: 'alerts',
        component: () => import('@/pages/AlertsPage.vue'),
        meta: { title: '告警中心', permission: 'alerts:read' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/pages/SettingsPage.vue'),
        meta: { title: '系统设置', permission: 'settings:read' },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: () => import('@/pages/ForbiddenPage.vue'),
        meta: { title: '权限不足' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/pages/NotFoundPage.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.path === from.path) return false
    return { top: 0, behavior: 'smooth' }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    if (auth.token) return { path: '/dashboard' }
    return true
  }
  if (!auth.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!auth.initialized) {
    await auth.fetchMe()
    if (!auth.token) return { name: 'login', query: { redirect: to.fullPath } }
  }
  const permission = to.meta.permission as string | undefined
  if (permission && !auth.can(permission)) {
    return { name: 'forbidden', query: { from: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || ''
  document.title = title ? `${title} · LISA 黎阳智能排产智能体` : 'LISA · 黎阳智能排产智能体'
})

export default router
