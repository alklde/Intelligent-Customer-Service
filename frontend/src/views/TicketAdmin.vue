<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { listTickets, patchTicket } from '../api.js'
import { auth } from '../auth.js'

const tickets = ref([])
const filter = ref('')
const onlyMine = ref(false)
const loading = ref(false)
const error = ref('')

const FILTERS = [
  { value: '', label: '全部' },
  { value: 'open', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
]

const NEXT_ACTION = {
  open: { to: 'processing', label: '开始处理' },
  processing: { to: 'resolved', label: '标记解决' },
  resolved: { to: 'closed', label: '归档关闭' },
  closed: null,
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    tickets.value = await listTickets(filter.value || null, onlyMine.value ? auth.subject : null)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function transition(t) {
  const action = NEXT_ACTION[t.status]
  if (!action) return
  try {
    await patchTicket(t.ticket_id, action.to)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

const fmtTime = (ts) => new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false })

let timer = null
onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div style="max-width: 1180px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">工单管理</h2>
        <p class="page-desc">AI 自动创建与人工补录的工单统一管理，支持状态流转</p>
      </div>
      <button class="btn ghost" :disabled="loading" @click="load">
        <span v-if="loading" class="spin"></span> 刷新
      </button>
    </div>

    <div style="display: flex; gap: 8px; margin: 16px 0; align-items: center">
      <button
        v-for="f in FILTERS" :key="f.value"
        class="btn" :class="filter === f.value ? '' : 'ghost'"
        style="padding: 6px 14px"
        @click="filter = f.value; load()"
      >{{ f.label }}</button>
      <label style="margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-dim); cursor: pointer">
        <input v-model="onlyMine" type="checkbox" @change="load" /> 只看我接的单
      </label>
    </div>

    <div v-if="error" class="error-banner" style="margin-bottom: 12px">{{ error }}</div>

    <div class="card" style="padding: 0; overflow: hidden">
      <table style="width: 100%; border-collapse: collapse; font-size: 13px">
        <thead>
          <tr style="color: var(--text-dim); text-align: left">
            <th style="padding: 12px 16px; font-weight: 500">工单号</th>
            <th style="padding: 12px 16px; font-weight: 500">问题描述</th>
            <th style="padding: 12px 16px; font-weight: 500">包裹单号</th>
            <th style="padding: 12px 16px; font-weight: 500">客户</th>
            <th style="padding: 12px 16px; font-weight: 500">接单客服</th>
            <th style="padding: 12px 16px; font-weight: 500">优先级</th>
            <th style="padding: 12px 16px; font-weight: 500">来源</th>
            <th style="padding: 12px 16px; font-weight: 500">创建时间</th>
            <th style="padding: 12px 16px; font-weight: 500">状态</th>
            <th style="padding: 12px 16px; font-weight: 500">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tickets" :key="t.ticket_id" style="border-top: 1px solid var(--border)">
            <td style="padding: 12px 16px; font-family: var(--mono); color: var(--accent)">{{ t.ticket_id }}</td>
            <td style="padding: 12px 16px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ t.issue_desc }}</td>
            <td style="padding: 12px 16px; font-family: var(--mono)">{{ t.package_no || '-' }}</td>
            <td style="padding: 12px 16px; font-size: 12px; color: var(--text-dim); font-family: var(--mono)">{{ t.user_id || '-' }}</td>
            <td style="padding: 12px 16px; font-size: 12px; font-family: var(--mono)">{{ t.agent_id || '待分配' }}</td>
            <td style="padding: 12px 16px">
              <span class="badge" :class="t.priority === 'high' ? 'danger' : 'info'">{{ t.priority }}</span>
            </td>
            <td style="padding: 12px 16px; color: var(--text-dim)">{{ t.source === 'ai' ? 'AI 创建' : '人工' }}</td>
            <td style="padding: 12px 16px; color: var(--text-dim); font-size: 12px">{{ fmtTime(t.created_at) }}</td>
            <td style="padding: 12px 16px">
              <span class="badge" :class="{ open: 'warn', processing: 'info', resolved: 'ok', closed: '' }[t.status]">{{ t.status }}</span>
            </td>
            <td style="padding: 12px 16px">
              <button v-if="NEXT_ACTION[t.status]" class="btn ghost" style="padding: 5px 12px" @click="transition(t)">
                {{ NEXT_ACTION[t.status].label }}
              </button>
              <span v-else style="color: var(--text-dim)">—</span>
            </td>
          </tr>
          <tr v-if="!tickets.length && !loading">
            <td colspan="10"><div class="empty">暂无工单</div></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
