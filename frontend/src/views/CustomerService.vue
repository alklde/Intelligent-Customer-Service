<script setup>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { csChatSession, csStreamUrl, getMySessionDetail, getMySessions } from '../api.js'
import { auth } from '../auth.js'

const STORAGE_KEY = `suite_cs_active_${auth.subject}`

const sessions = ref([])
const sessionId = ref('')
const input = ref('')
const sending = ref(false)
const messages = ref([])
const status = ref('ai_handling')
const intent = ref('-')
const toolCallCount = ref(0)
const chatBox = ref(null)
const error = ref('')

let es = null
let historyTimer = null
let lastEventId = '0'
const seenIds = new Set()

const intentLabel = { chitchat: '智能问答', query_order: '查订单', create_ticket: '提工单', human: '转人工', unknown: '-' }

const statusBanner = {
  pending_human: { text: '已转入人工队列，客服正在分配，请稍候...', cls: 'banner-warn' },
  human_handling: { text: '人工客服已接入，正在为您服务', cls: 'banner-ok' },
  closed: { text: '本会话已结束，点击「新会话」重新开始', cls: 'banner-dim' },
}

const statusMeta = {
  ai_handling: { label: 'AI 服务中', cls: 'ok' },
  pending_human: { label: '排队中', cls: 'warn' },
  human_handling: { label: '人工服务中', cls: 'ok' },
  closed: { label: '已结束', cls: '' },
}

const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false }) : '')

async function scrollToBottom() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

async function loadHistory() {
  try {
    sessions.value = await getMySessions()
  } catch {
    /* 历史加载失败不阻塞对话 */
  }
}

function openStream() {
  if (es) es.close()
  es = new EventSource(csStreamUrl(sessionId.value, lastEventId))
  es.onmessage = (e) => {
    const d = JSON.parse(e.data)
    if (seenIds.has(d.id)) return
    seenIds.add(d.id)
    lastEventId = d.id
    status.value = d.status
    if (d.source === 'human') {
      messages.value.push({ role: 'assistant', content: d.content, source: 'human' })
      scrollToBottom()
      loadHistory()
    }
  }
}

async function openSession(id) {
  if (!id) return
  error.value = ''
  try {
    const detail = await getMySessionDetail(id)
    es && es.close()
    es = null
    sessionId.value = id
    sessionStorage.setItem(STORAGE_KEY, id)
    status.value = detail.meta.status
    intent.value = detail.meta.intent_summary || '-'
    toolCallCount.value = Number(detail.meta.tool_call_count || 0)
    messages.value = detail.messages.map((m) => ({ role: m.role, content: m.content, source: m.source }))
    seenIds.clear()
    detail.messages.forEach((m) => seenIds.add(m.id))
    lastEventId = detail.messages.length ? detail.messages[detail.messages.length - 1].id : '0'
    if (status.value !== 'closed') openStream()
    await scrollToBottom()
  } catch (e) {
    error.value = e.message
    sessionStorage.removeItem(STORAGE_KEY)
  }
}

async function send(text) {
  const content = (text ?? input.value).trim()
  if (!content || sending.value) return
  messages.value.push({ role: 'user', content, source: 'user' })
  input.value = ''
  sending.value = true
  error.value = ''
  await scrollToBottom()
  try {
    const res = await csChatSession(sessionId.value || null, content, auth.subject)
    sessionId.value = res.session_id
    sessionStorage.setItem(STORAGE_KEY, res.session_id)
    status.value = res.status
    intent.value = res.intent
    toolCallCount.value = res.tool_call_count
    if (res.reply) messages.value.push({ role: 'assistant', content: res.reply, source: 'ai' })
    if (!es) openStream()
    await loadHistory()
  } catch (e) {
    error.value = e.message
    messages.value.push({ role: 'assistant', content: `[服务异常] ${e.message}`, source: 'ai' })
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

function reset() {
  es && es.close()
  es = null
  sessionId.value = ''
  messages.value = []
  status.value = 'ai_handling'
  intent.value = '-'
  toolCallCount.value = 0
  lastEventId = '0'
  seenIds.clear()
  error.value = ''
  sessionStorage.removeItem(STORAGE_KEY)
  loadHistory()
}

onMounted(async () => {
  await loadHistory()
  historyTimer = setInterval(loadHistory, 5000)
  const active = sessionStorage.getItem(STORAGE_KEY)
  if (active) await openSession(active)
})

onUnmounted(() => {
  es && es.close()
  if (historyTimer) clearInterval(historyTimer)
})
</script>

<template>
  <div class="cs-layout">
    <aside class="card history-panel">
      <div class="history-head">
        <span>历史会话</span>
        <button class="btn" style="padding: 6px 12px; font-size: 12px" @click="reset">新会话</button>
      </div>
      <div class="history-list">
        <div v-if="!sessions.length" class="empty" style="padding: 24px 0">暂无历史会话</div>
        <button
          v-for="s in sessions" :key="s.session_id"
          class="history-item" :class="{ active: s.session_id === sessionId }"
          @click="openSession(s.session_id)"
        >
          <div class="history-title">{{ s.title }}</div>
          <div class="history-preview">{{ s.last_message || '（空会话）' }}</div>
          <div class="history-meta">
            <span class="badge" :class="statusMeta[s.status]?.cls || 'info'" style="font-size: 11px">
              {{ statusMeta[s.status]?.label || s.status }}
            </span>
            <span>{{ fmtTime(s.updated_at) }}</span>
          </div>
        </button>
      </div>
    </aside>

    <section class="chat-panel">
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div>
          <h2 class="page-title">智能客服</h2>
          <p class="page-desc">AI 智能应答；复杂问题可转接人工，历史会话自动保存</p>
        </div>
        <span style="font-size: 12px; color: var(--text-dim); font-family: var(--mono)">
          {{ auth.name }} · {{ sessionId ? sessionId.slice(0, 8) : '新会话' }}
        </span>
      </div>

      <div v-if="error" class="error-banner">{{ error }}</div>
      <div v-if="statusBanner[status]" class="banner" :class="statusBanner[status].cls">
        {{ statusBanner[status].text }}
      </div>

      <div class="card meta-row">
        <span class="badge info">意图: {{ intentLabel[intent] || intent }}</span>
        <span class="badge" :class="toolCallCount ? 'warn' : 'ok'">工具失败: {{ toolCallCount }}/3</span>
        <span class="badge" :class="statusMeta[status]?.cls || 'info'">{{ statusMeta[status]?.label || status }}</span>
      </div>

      <div ref="chatBox" class="card chat-box">
        <div v-if="!messages.length" class="empty">
          开始对话，试试「发票怎么开」或「转人工」
        </div>
        <div
          v-for="(m, i) in messages" :key="i"
          :style="{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start' }"
          style="max-width: 78%; display: flex; flex-direction: column; gap: 3px"
        >
          <span v-if="m.source === 'human'" style="font-size: 11px; color: var(--ok); margin-left: 4px">人工客服</span>
          <div :class="m.role === 'user' ? 'bubble-user' : (m.source === 'human' ? 'bubble-human' : 'bubble-ai')" class="bubble">{{ m.content }}</div>
        </div>
        <div v-if="sending" style="align-self: flex-start" class="bubble bubble-ai">
          <span class="spin" style="border-top-color: var(--accent)"></span>
        </div>
      </div>

      <div style="display: flex; gap: 10px" v-if="status !== 'closed'">
        <input v-model="input" class="input" placeholder="输入消息，回车发送" @keyup.enter="send()" :disabled="sending" />
        <button class="btn ghost" :disabled="sending" @click="send('转人工')">转人工</button>
        <button class="btn" :disabled="sending || !input.trim()" @click="send()">发送</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.cs-layout { width: 100%; max-width: 1120px; height: calc(100vh - 150px); display: flex; gap: 14px; }
.history-panel { width: 270px; flex-shrink: 0; display: flex; flex-direction: column; padding: 12px; }
.history-head { display: flex; align-items: center; justify-content: space-between; font-weight: 600; font-size: 13px; padding: 2px 4px 10px; border-bottom: 1px solid var(--border); }
.history-list { flex: 1; overflow-y: auto; margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.history-item {
  text-align: left; background: transparent; border: 1px solid var(--border);
  border-radius: 10px; padding: 10px; cursor: pointer; font-family: inherit; color: var(--text);
  transition: all 0.15s; width: 100%;
}
.history-item:hover, .history-item.active { border-color: var(--accent); background: var(--accent-soft); }
.history-title { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-preview { font-size: 12px; color: var(--text-dim); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-meta { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; font-size: 11px; color: var(--text-dim); }
.chat-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.meta-row { display: flex; gap: 10px; padding: 10px 16px; align-items: center; }
.chat-box { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 20px; }

.bubble { padding: 10px 14px; border-radius: 14px; line-height: 1.6; font-size: 13px; }
.bubble-user { background: linear-gradient(135deg, var(--accent), #9d7cff); color: #fff; border-bottom-right-radius: 4px; }
.bubble-ai { background: var(--bg-soft); border: 1px solid var(--border-strong); border-bottom-left-radius: 4px; }
.bubble-human { background: rgba(61, 214, 140, 0.10); border: 1px solid rgba(61, 214, 140, 0.4); border-bottom-left-radius: 4px; }

.banner { padding: 10px 14px; border-radius: 9px; font-size: 13px; font-weight: 500; }
.banner-warn { background: rgba(240, 182, 76, 0.12); border: 1px solid rgba(240, 182, 76, 0.4); color: var(--warn); }
.banner-ok { background: rgba(61, 214, 140, 0.10); border: 1px solid rgba(61, 214, 140, 0.4); color: var(--ok); }
.banner-dim { background: var(--bg-soft); border: 1px solid var(--border-strong); color: var(--text-dim); }
</style>