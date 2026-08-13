import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      redirect: '/chat',
      children: [
        { path: 'chat', component: () => import('@/views/ChatView.vue') },
        { path: 'documents', component: () => import('@/views/DocumentView.vue') },
        { path: 'admin', component: () => import('@/views/AdminView.vue') },
      ],
    },
  ],
})

// 未登录访问受保护页面 -> 跳登录；非管理员进 /admin -> 回问答
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) {
    return '/login'
  }
  if (to.path === '/admin' && auth.user?.role !== 'admin') {
    return '/chat'
  }
  if (to.path === '/login' && auth.token) {
    return '/chat'
  }
})

export default router
