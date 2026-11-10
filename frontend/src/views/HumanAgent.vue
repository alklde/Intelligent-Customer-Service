<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import {
  claimSession,
  closeSessionApi,
  getPendingSessions,
  getSessionDetail,
  getSessionHistory,
  kbSearch,
  replySession,
} from '../api.js'
import { auth } from '../auth.js'

const STORAGE_KEY = `suite_staff_active_${auth.subject}`
const agentId = ref(auth.subject)
const tab = ref('pending')
const pendingList = ref([])
const historyList = ref([])
const currentId = ref('')
const detail = ref(null)
const input = ref('')
const sending = ref(false)
const error = ref('')
const pollTimer = ref(null)
const chatTimer = ref(null)
const historyTimer = ref(null)

const kbQuery = ref('')
const kbLoading = ref(false)
const kbAnswer = ref('')
const kbSources = ref([])
const kbFound = ref(false)

async function refreshQueue() {
  try {
    pendingList.value = await getPendingSessions()
  } catch { /* 后端短暂不可用时静默重试 */ }
}

async function refreshHistory() {
  try {
    historyList.value = await getSessionHistory()
  } catch { /* 历史加载失败不阻塞排队 */ }
}

async function openSession(id) {
  currentId.value = id
  sessionStorage.setItem(STORAGE_KEY, id)
  await loadDetail()
  if (detail.value && detail.value.meta.status === 'human_handling') startChatPolling()
}

async function loadDetail() {
  if (!currentId.value) return
  try {
    detail.value = await getSessionDetail(currentId.value)
  } catch (e) {
    error.value = e.message
    if (e.message.includes('不存在')) {
      currentId.value = ''
      detail.value = null
      sessionStorage.removeItem(STORAGE_KEY)
    }
  }
}

async function claim(item) {
  error.value = ''
  try {
    await claimSession(item.session_id, agentId.value)
    await refreshQueue()
    await refreshHistory()
    tab.value = 'pending'
    await openSession(item.session_id)
  } catch (e) {
    error.value = e.message
    await refreshQueue()
    await refreshHistory()
  }
}

async function sendReply() {
  const content = input.value.trim()
  if (!content || sending.value || !currentId.value) return
  sending.value = true
  try {
    await replySession(currentId.value, agentId.value, content)
    input.value = ''
    await loadDetail()
    await refreshHistory()
  } catch (e) {
    error.value = e.message
  } finally {
    sending.value = false
  }
}

async function finishSession(markBadcase) {
  try {
    await closeSessionApi(currentId.value, agentId.value, true, markBadcase, 'close')
    clearCurrent()
    await refreshQueue()
    await refreshHistory()
  } catch (e) {
    error.value = e.message
  }
}

async function backToAi() {
  try {
    await closeSessionApi(currentId.value, agentId.value, false, false, 'reopen')
    clearCurrent()
    await refreshQueue()
    await refreshHistory()
  } catch (e) {
    error.value = e.message
  }
}

function clearCurrent() {
  currentId.value = ''
  detail.value = null
  kbAnswer.value = ''
  kbSources.value = []
  stopChatPolling()
  sessionStorage.removeItem(STORAGE_KEY)
}

function startChatPolling() {
  stopChatPolling()
  chatTimer.value = setInterval(loadDetail, 1500)
}

function stopChatPolling() {
  if (chatTimer.value) clearInterval(chatTimer.value)
  chatTimer.value = null
}

function handleWindowFocus() {
  refreshQueue()
  refreshHistory()
  if (currentId.value) loadDetail()
}

async function searchKb() {
  const query = kbQuery.value.trim()
  if (!query || kbLoading.value || !currentId.value) return
  kbLoading.value = true
  kbAnswer.value = ''
  kbSources.value = []
  try {
    const result = await kbSearch(query, currentId.value)
    kbAnswer.value = result.answer
    kbSources.value = result.sources || []
    kbFound.value = result.found
  } catch (e) {
    error.value = e.message
  } finally {
    kbLoading.value = false
  }
}

function adoptAnswer() {
  if (kbAnswer.value) input.value = kbAnswer.value
}

onMounted(async () => {
  await refreshQueue()
  await refreshHistory()
  pollTimer.value = setInterval(refreshQueue, 2000)
  historyTimer.value = setInterval(refreshHistory, 5000)
  window.addEventListener('focus', handleWindowFocus)
  document.addEventListener('visibilitychange', handleWindowFocus)
  const active = sessionStorage.getItem(STORAGE_KEY)
  if (active) await openSession(active)
})
onUnmounted(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  if (historyTimer.value) clearInterval(historyTimer.value)
  window.removeEventListener('focus', handleWindowFocus)
  document.removeEventListener('visibilitychange', handleWindowFocus)
  stopChatPolling()
})

const statusLabel = { ai_handling: 'AI 处理中', pending_human: '待接入', human_handling: '人工处理中', closed: '已关闭' }
const statusBadge = { ai_handling: 'info', pending_human: 'warn', human_handling: 'ok', closed: '' }
const fmtTs = (ts) => new Date(Number(ts) * 1000).toLocaleTimeString('zh-CN', { hour12: false })
const fmtDate = (ts) => new Date(Number(ts) * 1000).toLocaleString('zh-CN', { hour12: false })
</script>

<template>
  <div style="height: calc(100vh - 56px); display: flex; flex-direction: column; gap: 14px">
    <div style="display: flex; align-items: center; gap: 14px">
      <div>
        <h2 class="page-title">人工客服工作台</h2>
        <p class="page-desc">接入会话后可使用知识库检索；历史会话与当前进度自动保存</p>
      </div>
      <div style="margin-left: auto; display: flex; align-items: center; gap: 8px">
        <span style="font-size: 12px; color: var(--text-dim)">工号</span>
        <span class="badge info" style="font-family: var(--mono)">{{ agentId }}</span>
        <span style="font-size: 12px; color: var(--text-dim)">{{ auth.name }}</span>
        <span class="badge ok">在线</span>
      </div>
    </div>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <div style="flex: 1; display: flex; gap: 14px; min-height: 0">
      <!-- 左栏: 待接入 / 我的会话 -->
      <div class="card" style="width: 320px; flex-shrink: 0; display: flex; flex-direction: column; padding: 12px">
        <div style="display: flex; gap: 8px; margin-bottom: 10px">
          <button class="btn" :class="tab === 'pending' ? '' : 'ghost'" style="flex: 1; padding: 7px" @click="tab = 'pending'">
            待接入 ({{ pendingList.length }})
          </button>
          <button class="btn" :class="tab === 'history' ? '' : 'ghost'" style="flex: 1; padding: 7px" @click="tab = 'history'; refreshHistory()">
            我的会话 ({{ historyList.length }})
          </button>
        </div>

        <div style="flex: 1; overflow-y: auto">
          <template v-if="tab === 'pending'">
            <div v-if="!pendingList.length" class="empty" style="padding: 24px 0">队列为空</div>
            <div
              v-for="s in pendingList" :key="s.session_id"
              class="queue-item" :class="{ active: s.session_id === currentId }"
              @click="openSession(s.session_id)"
            >
              <div style="display: flex; justify-content: space-between; align-items: center">
                <span class="badge" :class="s.priority === 'high' ? 'danger' : 'info'">{{ s.priority === 'high' ? '高优先级' : '普通' }}</span>
                <span style="font-size: 11px; color: var(--text-dim); font-family: var(--mono)">等待 {{ s.waiting_seconds }}s</span>
              </div>
              <div style="font-size: 12px; margin-top: 6px; color: var(--text-dim)">意图: {{ s.intent_summary || '-' }} · {{ s.user_id }}</div>
              <div style="font-size: 12px; color: var(--text-dim); font-family: var(--mono)">{{ s.session_id.slice(0, 12) }}...</div>
              <button class="btn" style="width: 100%; margin-top: 8px; padding: 6px" @click.stop="claim(s)">接入会话</button>
            </div>
          </template>

          <template v-else>
            <div v-if="!historyList.length" class="empty" style="padding: 24px 0">暂无历史会话</div>
            <div
              v-for="s in historyList" :key="s.session_id"
              class="queue-item" :class="{ active: s.session_id === currentId }"
              @click="openSession(s.session_id)"
            >
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px">
                <strong style="font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ s.title }}</strong>
                <span class="badge" :class="statusBadge[s.status] || 'info'" style="font-size: 11px">{{ statusLabel[s.status] || s.status }}</span>
              </div>
              <div style="font-size: 11px; color: var(--text-dim); margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ s.last_message }}</div>
              <div style="font-size: 11px; color: var(--text-dim); margin-top: 4px; font-family: var(--mono)">{{ fmtDate(s.updated_at) }}</div>
            </div>
          </template>
        </div>
      </div>

      <!-- 中栏: 聊天窗 -->
      <div class="card" style="flex: 1; display: flex; flex-direction: column; padding: 16px; min-width: 0">
        <template v-if="detail">
          <div style="display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px; border-bottom: 1px solid var(--border)">
            <div>
              <strong style="font-size: 13px">{{ detail.meta.title || detail.meta.user_id }}</strong>
              <span style="font-size: 12px; color: var(--text-dim); margin-left: 8px; font-family: var(--mono)">{{ currentId.slice(0, 12) }}</span>
            </div>
            <span class="badge" :class="statusBadge[detail.meta.status] || 'info'">{{ statusLabel[detail.meta.status] || detail.meta.status }}</span>
          </div>
          <div style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 14px 2px">
            <div
              v-for="m in detail.messages" :key="m.id"
              :style="{ alignSelf: m.source === 'human' ? 'flex-end' : 'flex-start' }"
              style="max-width: 80%; display: flex; flex-direction: column; gap: 3px"
            >
              <span :style="{ textAlign: m.source === 'human' ? 'right' : 'left', fontSize: '11px', color: 'var(--text-dim)' }">
                {{ { user: '用户', ai: 'AI 客服', human: `我（客服 ${detail.meta.agent_id || ''}）` }[m.source] }} · {{ fmtTs(m.ts) }}
              </span>
              <div class="bubble" :class="m.source === 'human' ? 'bubble-agent' : (m.source === 'user' ? 'bubble-user' : 'bubble-ai')">{{ m.content }}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px">
            <input
              v-model="input" class="input" placeholder="输入回复，回车发送" @keyup.enter="sendReply"
              :disabled="sending || detail.meta.status !== 'human_handling'"
            />
            <button class="btn" :disabled="sending || !input.trim() || detail.meta.status !== 'human_handling'" @click="sendReply">发送</button>
          </div>
        </template>
        <div v-else class="empty" style="margin: auto">点击左侧待接入或历史会话查看详情</div>
      </div>

      <!-- 右栏: 上下文 / 知识库 / 操作 -->
      <div class="card" style="width: 300px; flex-shrink: 0; overflow-y: auto; padding: 14px" v-if="detail">
        <div style="font-weight: 600; font-size: 13px; margin-bottom: 10px">AI 阶段上下文</div>
        <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px">
          <div style="display: flex; justify-content: space-between; font-size: 12px">
            <span style="color: var(--text-dim)">识别意图</span><span>{{ detail.meta.intent_summary || '-' }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px">
            <span style="color: var(--text-dim)">工具失败</span><span>{{ detail.meta.tool_call_count || 0 }}/3</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px">
            <span style="color: var(--text-dim)">badcase</span>
            <span :class="detail.meta.badcase ? 'danger-text' : ''">{{ detail.meta.badcase ? '是' : '否' }}</span>
          </div>
        </div>

        <template v-if="detail.meta.status === 'human_handling'">
          <div style="font-weight: 600; font-size: 13px; margin-bottom: 8px">知识库检索</div>
          <div style="display: flex; gap: 6px; margin-bottom: 8px">
            <input v-model="kbQuery" class="input" style="padding: 7px 10px" placeholder="检索问题" @keyup.enter="searchKb" />
            <button class="btn ghost" style="padding: 6px 12px" :disabled="kbLoading || !kbQuery.trim()" @click="searchKb">查</button>
          </div>
          <div v-if="kbLoading" class="empty" style="padding: 12px 0"><span class="spin"></span></div>
          <div v-else-if="kbAnswer" class="kb-result">
            <div class="kb-answer">{{ kbAnswer }}</div>
            <div v-if="!kbFound" style="margin-top: 6px; font-size: 11px; color: var(--warn)">知识库未命中，建议直接答复或转回 AI</div>
            <button class="btn ghost" style="width: 100%; margin-top: 8px; padding: 5px" @click="adoptAnswer">填入回复</button>
            <div v-if="kbSources.length" style="margin-top: 8px; font-size: 11px; color: var(--text-dim)">
              依据：
              <div v-for="(s, i) in kbSources.slice(0, 3)" :key="i">· {{ s.title || '知识片段' }}</div>
            </div>
          </div>

          <div style="font-weight: 600; font-size: 13px; margin: 14px 0 8px">操作</div>
          <div style="display: flex; flex-direction: column; gap: 8px">
            <button class="btn" @click="finishSession(false)">解决并关闭会话</button>
            <button class="btn ghost" @click="finishSession(true)">标记 badcase 并关闭</button>
            <button class="btn ghost" @click="backToAi">转回 AI 接管</button>
          </div>
        </template>

        <div style="font-weight: 600; font-size: 13px; margin: 14px 0 8px">转人工原因上下文</div>
        <div
          v-for="m in (detail.meta.context_snapshot ? JSON.parse(detail.meta.context_snapshot) : [])" :key="m.id"
          style="font-size: 12px; color: var(--text-dim); padding: 6px 0; border-bottom: 1px dashed var(--border)"
        >
          <span style="color: var(--accent)">{{ { user: '用户', ai: 'AI', human: '客服' }[m.source] }}:</span>
          {{ m.content.slice(0, 50) }}{{ m.content.length > 50 ? '...' : '' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble { padding: 9px 13px; border-radius: 12px; line-height: 1.6; font-size: 13px; display: inline-block; }
.bubble-agent { background: linear-gradient(135deg, var(--accent), #9d7cff); color: #fff; border-bottom-right-radius: 4px; }
.bubble-user { background: rgba(124, 108, 255, 0.10); border: 1px solid rgba(124, 108, 255, 0.35); border-bottom-left-radius: 4px; }
.bubble-ai { background: var(--bg-soft); border: 1px solid var(--border-strong); border-bottom-left-radius: 4px; }

.queue-item {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.queue-item:hover, .queue-item.active { border-color: var(--accent); background: var(--accent-soft); }
.danger-text { color: var(--danger); font-weight: 600; }
.kb-result { border: 1px solid var(--border); border-radius: 10px; padding: 10px; background: var(--bg-soft); }
.kb-answer { font-size: 12px; line-height: 1.7; color: var(--text); max-height: 160px; overflow-y: auto; }
</style>