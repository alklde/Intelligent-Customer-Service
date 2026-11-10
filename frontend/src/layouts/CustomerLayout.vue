<script setup>
import { RouterLink, useRouter } from 'vue-router'
import { auth, clearAuth } from '../auth.js'
import { customerLogout } from '../api.js'

const router = useRouter()

async function logout() {
  try {
    await customerLogout()
  } catch {
    /* 令牌可能已失效，本地清理即可 */
  } finally {
    clearAuth()
    router.replace('/login')
  }
}
</script>

<template>
  <div class="customer-shell">
    <header class="customer-nav">
      <div class="customer-brand">
        <div class="brand-mark">AI</div>
        <div class="brand-text">
          <h1>客户服务门户</h1>
          <p>Agentic 智能客服</p>
        </div>
      </div>
      <nav class="customer-links">
        <RouterLink to="/service" class="nav-item" active-class="active">在线客服</RouterLink>
        <RouterLink to="/my-applications" class="nav-item" active-class="active">我的申请</RouterLink>
      </nav>
      <div class="customer-user">
        <span class="badge info">{{ auth.name || auth.subject }}</span>
        <button class="btn ghost" style="padding: 7px 14px" @click="logout">退出</button>
      </div>
    </header>
    <main class="customer-main">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.customer-shell { min-height: 100vh; display: flex; flex-direction: column; }
.customer-nav {
  display: flex; align-items: center; gap: 28px;
  padding: 12px 28px; background: var(--bg-soft);
  border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 10;
}
.customer-brand { display: flex; align-items: center; gap: 12px; }
.customer-links { display: flex; gap: 6px; }
.customer-links .nav-item { padding: 8px 14px; }
.customer-user { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.customer-main { flex: 1; padding: 26px 32px; display: flex; justify-content: center; }
</style>