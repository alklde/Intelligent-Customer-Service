<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  createAgent,
  createUser,
  getAdminStatus,
  listAgents,
  listUsers,
  updateAgent,
  updateUser,
  initAdmin,
} from '../api.js'

const initialized = ref(true)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const tab = ref('users')

const users = ref([])
const agents = ref([])

const initForm = reactive({ employee_id: '', secret: '', name: '系统管理员', bootstrap_key: '' })
const userForm = reactive({ username: '', password: '', nickname: '', phone: '' })
const agentForm = reactive({ employee_id: '', secret: '', name: '', role: 'agent' })

async function loadStatus() {
  try {
    const status = await getAdminStatus()
    initialized.value = status.initialized
  } catch (e) {
    error.value = e.message
  }
}

async function loadUsers() {
  users.value = await listUsers()
}

async function loadAgents() {
  agents.value = await listAgents()
}

async function refreshAll() {
  loading.value = true
  error.value = ''
  try {
    await loadStatus()
    if (initialized.value) {
      await Promise.all([loadUsers(), loadAgents()])
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function submitInit() {
  error.value = ''
  notice.value = ''
  try {
    await initAdmin({ ...initForm })
    notice.value = '管理员初始化成功，请使用该工号与密钥前往客服登录'
    initialized.value = true
    initForm.secret = ''
    initForm.bootstrap_key = ''
  } catch (e) {
    error.value = e.message
  }
}

async function addUser() {
  error.value = ''
  notice.value = ''
  try {
    await createUser({ ...userForm })
    notice.value = `客户 ${userForm.username} 已创建`
    Object.assign(userForm, { username: '', password: '', nickname: '', phone: '' })
    await loadUsers()
  } catch (e) {
    error.value = e.message
  }
}

async function addAgent() {
  error.value = ''
  notice.value = ''
  try {
    await createAgent({ ...agentForm })
    notice.value = `客服 ${agentForm.employee_id} 已创建`
    Object.assign(agentForm, { employee_id: '', secret: '', name: '', role: 'agent' })
    await loadAgents()
  } catch (e) {
    error.value = e.message
  }
}

async function resetUserPassword(user) {
  const password = window.prompt(`为客户 ${user.username} 设置新密码（至少 6 位）`)
  if (!password) return
  try {
    await updateUser(user.user_id, { password })
    notice.value = `已重置 ${user.username} 的密码`
  } catch (e) {
    error.value = e.message
  }
}

async function toggleUser(user) {
  const status = user.status === 'active' ? 'disabled' : 'active'
  try {
    await updateUser(user.user_id, { status })
    await loadUsers()
  } catch (e) {
    error.value = e.message
  }
}

async function resetAgentSecret(agent) {
  const secret = window.prompt(`为客服 ${agent.employee_id} 设置新密钥（至少 8 位）`)
  if (!secret) return
  try {
    await updateAgent(agent.employee_id, { secret })
    notice.value = `已重置 ${agent.employee_id} 的密钥`
  } catch (e) {
    error.value = e.message
  }
}

async function toggleAgent(agent) {
  const status = agent.status === 'active' ? 'disabled' : 'active'
  try {
    await updateAgent(agent.employee_id, { status })
    await loadAgents()
  } catch (e) {
    error.value = e.message
  }
}

const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false }) : '-')

let timer = null
onMounted(() => {
  refreshAll()
  timer = setInterval(refreshAll, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div style="max-width: 1080px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">数据库管理</h2>
        <p class="page-desc">仅管理员可见：维护客户账号、客服工号与密钥，重置凭据与启停用</p>
      </div>
      <button class="btn ghost" :disabled="loading" @click="refreshAll">刷新</button>
    </div>

    <div v-if="error" class="error-banner" style="margin-top: 14px">{{ error }}</div>
    <div v-if="notice" class="notice-banner" style="margin-top: 14px">{{ notice }}</div>

    <!-- 未初始化：引导初始化管理员 -->
    <div v-if="!initialized" class="card" style="margin-top: 18px; max-width: 520px">
      <h3 style="font-size: 16px; margin-bottom: 6px">初始化管理员</h3>
      <p class="page-desc" style="margin-bottom: 16px">系统尚未初始化。请创建第一个管理员账号，之后所有管理员均从此页面管理。</p>
      <label class="field"><span>管理员工号</span><input v-model="initForm.employee_id" class="input" placeholder="例如 admin001" /></label>
      <label class="field"><span>登录密钥</span><input v-model="initForm.secret" class="input" type="password" placeholder="至少 8 位" /></label>
      <label class="field"><span>姓名</span><input v-model="initForm.name" class="input" /></label>
      <label class="field"><span>初始化引导密钥</span><input v-model="initForm.bootstrap_key" class="input" placeholder="见 README / .env 的 ADMIN_BOOTSTRAP_KEY" /></label>
      <button class="btn" style="width: 100%" @click="submitInit">创建管理员</button>
    </div>

    <template v-else>
      <div style="display: flex; gap: 8px; margin: 18px 0 14px">
        <button class="btn" :class="tab === 'users' ? '' : 'ghost'" @click="tab = 'users'">客户账号（{{ users.length }}）</button>
        <button class="btn" :class="tab === 'agents' ? '' : 'ghost'" @click="tab = 'agents'">客服账号（{{ agents.length }}）</button>
      </div>

      <!-- 客户账号 -->
      <template v-if="tab === 'users'">
        <div class="card" style="margin-bottom: 16px">
          <div style="font-weight: 600; font-size: 13px; margin-bottom: 12px">新增客户</div>
          <div class="form-grid">
            <input v-model="userForm.username" class="input" placeholder="用户名（3-24 位）" />
            <input v-model="userForm.password" class="input" type="password" placeholder="密码（至少 6 位）" />
            <input v-model="userForm.nickname" class="input" placeholder="昵称" />
            <input v-model="userForm.phone" class="input" placeholder="手机号（可选）" />
            <button class="btn" @click="addUser">创建</button>
          </div>
        </div>
        <div class="card" style="padding: 0; overflow: hidden">
          <table class="db-table">
            <thead>
              <tr><th>用户 ID</th><th>用户名</th><th>昵称</th><th>手机号</th><th>状态</th><th>创建时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="u in users" :key="u.user_id">
                <td class="mono">{{ u.user_id }}</td>
                <td>{{ u.username }}</td>
                <td>{{ u.nickname }}</td>
                <td>{{ u.phone || '-' }}</td>
                <td><span class="badge" :class="u.status === 'active' ? 'ok' : 'danger'">{{ u.status === 'active' ? '正常' : '停用' }}</span></td>
                <td class="dim">{{ fmtTime(u.created_at) }}</td>
                <td class="actions">
                  <button class="btn ghost" @click="resetUserPassword(u)">重置密码</button>
                  <button class="btn ghost" @click="toggleUser(u)">{{ u.status === 'active' ? '停用' : '启用' }}</button>
                </td>
              </tr>
              <tr v-if="!users.length"><td colspan="7"><div class="empty">暂无客户账号</div></td></tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 客服账号 -->
      <template v-else>
        <div class="card" style="margin-bottom: 16px">
          <div style="font-weight: 600; font-size: 13px; margin-bottom: 12px">新增客服</div>
          <div class="form-grid">
            <input v-model="agentForm.employee_id" class="input" placeholder="工号（3-24 位）" />
            <input v-model="agentForm.secret" class="input" type="password" placeholder="密钥（至少 8 位）" />
            <input v-model="agentForm.name" class="input" placeholder="姓名" />
            <select v-model="agentForm.role" class="input">
              <option value="agent">客服</option>
              <option value="admin">管理员</option>
            </select>
            <button class="btn" @click="addAgent">创建</button>
          </div>
        </div>
        <div class="card" style="padding: 0; overflow: hidden">
          <table class="db-table">
            <thead>
              <tr><th>工号</th><th>姓名</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in agents" :key="a.employee_id">
                <td class="mono">{{ a.employee_id }}</td>
                <td>{{ a.name }}</td>
                <td><span class="badge" :class="a.role === 'admin' ? 'danger' : 'info'">{{ a.role === 'admin' ? '管理员' : '客服' }}</span></td>
                <td><span class="badge" :class="a.status === 'active' ? 'ok' : 'danger'">{{ a.status === 'active' ? '正常' : '停用' }}</span></td>
                <td class="dim">{{ fmtTime(a.created_at) }}</td>
                <td class="actions">
                  <button class="btn ghost" @click="resetAgentSecret(a)">重置密钥</button>
                  <button class="btn ghost" @click="toggleAgent(a)">{{ a.status === 'active' ? '停用' : '启用' }}</button>
                </td>
              </tr>
              <tr v-if="!agents.length"><td colspan="6"><div class="empty">暂无客服账号</div></td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 7px; margin-bottom: 12px; }
.field span { font-size: 12px; color: var(--text-dim); }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; align-items: center; }
.notice-banner { background: rgba(61, 214, 140, 0.10); border: 1px solid rgba(61, 214, 140, 0.35); color: var(--ok); padding: 10px 14px; border-radius: 9px; font-size: 13px; }
.db-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.db-table th { text-align: left; padding: 12px 14px; color: var(--text-dim); font-weight: 500; }
.db-table td { padding: 11px 14px; border-top: 1px solid var(--border); }
.db-table .mono { font-family: var(--mono); color: var(--accent); }
.db-table .dim { color: var(--text-dim); font-size: 12px; }
.db-table .actions { display: flex; gap: 8px; }
.db-table .actions .btn { padding: 5px 11px; font-size: 12px; }
</style>