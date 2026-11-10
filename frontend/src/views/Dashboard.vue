<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getStats } from '../api.js'

const stats = ref(null)
const error = ref('')
let timer = null

const CARDS = [
  { key: 'total_user_messages', label: '用户消息数' },
  { key: 'total_sessions_ai_replied', label: 'AI 应答轮次' },
  { key: 'transferred_human', label: '转人工次数', color: 'var(--warn)' },
  { key: 'sessions_claimed', label: '人工接入' },
  { key: 'human_replies', label: '人工回复数' },
  { key: 'sessions_resolved', label: '解决会话', color: 'var(--ok)' },
  { key: 'tickets_created', label: '新建工单' },
  { key: 'badcases', label: 'badcase', color: 'var(--danger)' },
]

async function load() {
  try {
    stats.value = await getStats()
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div style="max-width: 960px">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <div>
        <h2 class="page-title">运营统计</h2>
        <p class="page-desc">当日客服体系运行指标，每 10 秒自动刷新</p>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="error" class="error-banner" style="margin-top: 16px">{{ error }}</div>

    <template v-if="stats">
      <div class="metric-grid" style="margin-top: 20px">
        <div v-for="c in CARDS" :key="c.key" class="metric-card">
          <div class="metric-label">{{ c.label }}</div>
          <div class="metric-value" :style="c.color ? { color: c.color } : {}">{{ stats[c.key] }}</div>
        </div>
      </div>

      <div class="card" style="margin-top: 16px; display: flex; align-items: center; justify-content: space-between">
        <div>
          <div class="metric-label">当前待接入队列</div>
          <div class="metric-value" :style="{ color: stats.pending_queue_size ? 'var(--warn)' : 'var(--ok)' }">
            {{ stats.pending_queue_size }}
          </div>
        </div>
        <div style="font-size: 12px; color: var(--text-dim); text-align: right">
          统计日期: {{ stats.generated_at }}<br />
          <span class="dot" style="display: inline-block; margin-right: 6px"></span>实时采自 Redis
        </div>
      </div>
    </template>
  </div>
</template>
