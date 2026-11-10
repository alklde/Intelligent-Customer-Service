<script setup>
import { RouterLink, useRouter } from 'vue-router'
import { auth, clearAuth, isAdmin } from '../auth.js'
import { staffLogout } from '../api.js'

const router = useRouter()

async function logout() {
  try {
    await staffLogout()
  } catch {
    /* 令牌可能已失效，本地清理即可 */
  } finally {
    clearAuth()
    router.replace('/staff/login')
  }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div class="brand-text">
          <h1>Agent Suite</h1>
          <p>客服工作台</p>
        </div>
      </div>
      <nav>
        <RouterLink to="/staff/workbench" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          人工客服工作台
        </RouterLink>
        <RouterLink to="/staff/tickets" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
          工单管理
        </RouterLink>
        <RouterLink to="/staff/dashboard" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
          运营统计
        </RouterLink>
        <RouterLink to="/staff/eval" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M19 9l-5 5-4-4-3 3"/></svg>
          评测与护栏
        </RouterLink>
        <RouterLink v-if="isAdmin" to="/staff/knowledge" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
          知识库管理
        </RouterLink>
        <RouterLink v-if="isAdmin" to="/staff/database" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
          数据库管理
        </RouterLink>
      </nav>
      <div class="sidebar-user">
        <div>
          <div class="sidebar-user-name">{{ auth.name || auth.subject }}</div>
          <div class="sidebar-user-role">{{ isAdmin ? '管理员' : '客服' }} · {{ auth.subject }}</div>
        </div>
        <button class="btn ghost" style="padding: 6px 12px; font-size: 12px" @click="logout">退出</button>
      </div>
      <div class="sidebar-footer">
        <span class="dot"></span> 服务运行中 · 工号 {{ auth.subject }}
      </div>
    </aside>
    <main class="main">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.sidebar-user {
  margin-top: auto; padding: 12px; border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.sidebar-user-name { font-size: 13px; font-weight: 600; }
.sidebar-user-role { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.sidebar-footer { margin-top: 10px; }
</style>