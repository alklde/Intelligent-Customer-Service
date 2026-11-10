<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { getMyTickets } from '../api.js'

const tickets = ref([])
const loading = ref(false)
const error = ref('')
let timer = null

const STATUS = {
  open: { label: '待处理', cls: 'warn' },
  processing: { label: '处理中', cls: 'info' },
  resolved: { label: '已解决', cls: 'ok' },
  closed: { label: '已关闭', cls: '' },
}

async function load() {
  loading.value = true
  try {
    tickets.value = await getMyTickets()
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false }) : '-')

onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div style="width: 100%; max-width: 960px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">我的申请</h2>
        <p class="page-desc">你提交的客服申请单，可查看包裹单号、处理进度与接单客服</p>
      </div>
      <div style="display: flex; gap: 8px">
        <RouterLink to="/service" class="btn" style="text-decoration: none">新建咨询</RouterLink>
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="error" class="error-banner" style="margin-top: 14px">{{ error }}</div>

    <div class="card" style="margin-top: 16px; padding: 0; overflow: hidden">
      <table style="width: 100%; border-collapse: collapse; font-size: 13px">
        <thead>
          <tr style="color: var(--text-dim); text-align: left">
            <th style="padding: 12px 16px; font-weight: 500">工单号</th>
            <th style="padding: 12px 16px; font-weight: 500">包裹单号</th>
            <th style="padding: 12px 16px; font-weight: 500">问题描述</th>
            <th style="padding: 12px 16px; font-weight: 500">优先级</th>
            <th style="padding: 12px 16px; font-weight: 500">状态</th>
            <th style="padding: 12px 16px; font-weight: 500">接单客服</th>
            <th style="padding: 12px 16px; font-weight: 500">提交时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tickets" :key="t.ticket_id" style="border-top: 1px solid var(--border)">
            <td style="padding: 12px 16px; font-family: var(--mono); color: var(--accent)">{{ t.ticket_id }}</td>
            <td style="padding: 12px 16px; font-family: var(--mono)">{{ t.package_no || '-' }}</td>
            <td style="padding: 12px 16px; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ t.issue_desc }}</td>
            <td style="padding: 12px 16px">
              <span class="badge" :class="t.priority === 'high' ? 'danger' : 'info'">{{ t.priority === 'high' ? '高' : '普通' }}</span>
            </td>
            <td style="padding: 12px 16px">
              <span class="badge" :class="STATUS[t.status]?.cls || ''">{{ STATUS[t.status]?.label || t.status }}</span>
            </td>
            <td style="padding: 12px 16px; font-family: var(--mono)">{{ t.agent_id || '待分配' }}</td>
            <td style="padding: 12px 16px; color: var(--text-dim); font-size: 12px">{{ fmtTime(t.created_at) }}</td>
          </tr>
          <tr v-if="!tickets.length && !loading">
            <td colspan="7"><div class="empty">还没有申请单，去「在线客服」发起咨询吧</div></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>