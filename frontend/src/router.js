import { createRouter, createWebHistory } from 'vue-router'
import { auth, homePath } from './auth.js'
import CustomerService from './views/CustomerService.vue'
import EvalDashboard from './views/EvalDashboard.vue'
import HumanAgent from './views/HumanAgent.vue'
import TicketAdmin from './views/TicketAdmin.vue'
import Dashboard from './views/Dashboard.vue'
import Login from './views/Login.vue'
import StaffLogin from './views/StaffLogin.vue'
import MyApplications from './views/MyApplications.vue'
import DatabaseAdmin from './views/DatabaseAdmin.vue'
import KnowledgeAdmin from './views/KnowledgeAdmin.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: () => homePath() },

    // 登录页（访客）
    { path: '/login', component: Login, meta: { layout: 'blank', guest: true } },
    { path: '/staff/login', component: StaffLogin, meta: { layout: 'blank', guest: true } },

    // 客户区（知识库不直接对客户开放）
    { path: '/service', component: CustomerService, meta: { layout: 'customer', roles: ['customer'] } },
    { path: '/my-applications', component: MyApplications, meta: { layout: 'customer', roles: ['customer'] } },

    // 客服区
    { path: '/staff/workbench', component: HumanAgent, meta: { layout: 'staff', roles: ['agent', 'admin'] } },
    { path: '/staff/tickets', component: TicketAdmin, meta: { layout: 'staff', roles: ['agent', 'admin'] } },
    { path: '/staff/dashboard', component: Dashboard, meta: { layout: 'staff', roles: ['agent', 'admin'] } },
    { path: '/staff/eval', component: EvalDashboard, meta: { layout: 'staff', roles: ['agent', 'admin'] } },
    { path: '/staff/knowledge', component: KnowledgeAdmin, meta: { layout: 'staff', roles: ['admin'] } },
    { path: '/staff/database', component: DatabaseAdmin, meta: { layout: 'staff', roles: ['admin'] } },

    // 兼容旧地址
    { path: '/agent', redirect: '/staff/workbench' },
    { path: '/tickets', redirect: '/staff/tickets' },
    { path: '/dashboard', redirect: '/staff/dashboard' },
    { path: '/eval', redirect: '/staff/eval' },
    { path: '/rag', redirect: '/service' },
  ],
})

router.beforeEach((to) => {
  const logged = Boolean(auth.token)

  if (to.meta.guest) {
    return logged ? homePath() : true
  }

  const roles = to.meta.roles
  if (!roles) return true
  if (!logged) {
    const loginPath = roles.includes('customer') ? '/login' : '/staff/login'
    return { path: loginPath, query: { redirect: to.fullPath } }
  }
  if (!roles.includes(auth.role)) {
    return auth.role === 'customer' ? '/service' : '/staff/workbench'
  }
  return true
})

export default router