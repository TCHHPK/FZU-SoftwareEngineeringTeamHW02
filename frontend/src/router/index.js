import { createRouter, createWebHistory } from 'vue-router'
import BasicLayout from '@/layouts/BasicLayout.vue'

const routes = [
  // 👇 登录页和注册页放在最外面（全屏独立页面，无左侧菜单）
  { 
    path: '/login', 
    name: 'Login', 
    component: () => import('@/views/LoginView.vue') 
  },
  { 
    path: '/register', 
    name: 'Register', 
    component: () => import('@/views/RegisterView.vue') 
  },

  // 👇 其他需要左侧菜单的页面，全部包在 BasicLayout 里
  {
    path: '/',
    component: BasicLayout,
    redirect: '/upload',
    children: [
      { path: 'upload', name: 'Upload', component: () => import('@/views/UploadView.vue') },
      { path: 'sessions', name: 'Sessions', component: () => import('@/views/SessionsView.vue') },
      { path: 'self-tests', name: 'SelfTest', component: () => import('@/views/SelfTestView.vue') },
      { path: 'wrong-book', name: 'WrongBook', component: () => import('@/views/WrongBookView.vue') },
      { path: 'sessions/:id/progress', name: 'Progress', component: () => import('@/views/ProgressView.vue') },
      { path: 'sessions/:id/result', name: 'Result', component: () => import('@/views/ResultView.vue') },
      { path: 'chat', name: 'Chat', component: () => import('@/views/ChatView.vue') }
    ]
  },
  
  { path: '/:pathMatch(.*)*', redirect: '/upload' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router