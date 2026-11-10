/** 统一请求封装：自动附带令牌、提取错误详情、401 统一登出。 */
import { clearAuth, getToken } from './auth.js'

const request = async (url, options = {}) => {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(url, { ...options, headers })
  if (res.status === 401 && !url.includes('/auth/login')) {
    const wasStaff = window.location.pathname.startsWith('/staff')
    clearAuth()
    window.location.href = wasStaff ? '/staff/login' : '/login'
    throw new Error('登录已过期，请重新登录')
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `请求失败 (${res.status})`)
  }
  return res.json()
}

const post = (url, body) => request(url, { method: 'POST', body: JSON.stringify(body) })

// ===== 认证：客户端 =====
export const getCustomerCaptcha = () => request('/api/cs/auth/captcha')
export const customerLogin = (payload) => post('/api/cs/auth/login', payload)
export const customerLogout = () => post('/api/cs/auth/logout', {})
export const customerMe = () => request('/api/cs/auth/me')

// ===== 认证：客服端 =====
export const getStaffCaptcha = () => request('/api/admin/auth/captcha')
export const staffLogin = (payload) => post('/api/admin/auth/login', payload)
export const staffLogout = () => post('/api/admin/auth/logout', {})
export const staffMe = () => request('/api/admin/auth/me')

// ===== 知识库管理（管理员） =====
export const listKbDocuments = () => request('/api/rag/kb/documents')
export const createKbDocument = (payload) => post('/api/rag/kb/documents', payload)
export const deleteKbDocument = (docId) =>
  request(`/api/rag/kb/documents/${docId}`, { method: 'DELETE' })
export const reindexKb = () => post('/api/rag/kb/reindex', {})

// ===== 知识库检索（客服，限本人在处理的会话） =====
export const kbSearch = (query, session_id) =>
  post('/api/rag/kb/search', { query, session_id })

// ===== 评测与护栏 =====
export const runEval = () => post('/api/eval/evaluate', {})
export const guardrailCheck = (trace, allowed_tools) =>
  post('/api/eval/guardrails/check', { trace, allowed_tools })

// ===== 客户会话（proj2） =====
export const csChatSession = (session_id, message, user_id) =>
  post('/api/cs/chat', { session_id, message, user_id })

export const csStreamUrl = (session_id, last_id = '0') =>
  `/api/cs/chat/stream?session_id=${session_id}&last_id=${encodeURIComponent(last_id)}&token=${encodeURIComponent(getToken())}`

export const getMySessions = () => request('/api/cs/my/sessions')
export const getMySessionDetail = (id) => request(`/api/cs/my/sessions/${id}`)
export const getMyTickets = () => request('/api/cs/my/tickets')

// ===== 客服工作台（proj4） =====
export const getPendingSessions = () => request('/api/admin/sessions/pending')
export const getSessionHistory = () => request('/api/admin/sessions/history')
export const getSessionDetail = (id) => request(`/api/admin/sessions/${id}`)
export const claimSession = (id, agent_id) => post(`/api/admin/sessions/${id}/claim`, { agent_id })
export const replySession = (id, agent_id, content) =>
  post(`/api/admin/sessions/${id}/reply`, { agent_id, content })
export const closeSessionApi = (id, agent_id, resolve, mark_badcase, action = 'close') =>
  post(`/api/admin/sessions/${id}/close`, { agent_id, resolve, mark_badcase, action })

export const listTickets = (status, agent_id) => {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (agent_id) params.set('agent_id', agent_id)
  const query = params.toString()
  return request(`/api/admin/tickets${query ? `?${query}` : ''}`)
}

export const patchTicket = (id, status) =>
  request(`/api/admin/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })

export const getStats = () => request('/api/admin/stats/today')

// ===== 管理员：数据库管理 =====
export const getAdminStatus = () => request('/api/admin/admin/status')
export const initAdmin = (payload) => post('/api/admin/admin/init', payload)

export const listUsers = () => request('/api/admin/admin/users')
export const createUser = (payload) => post('/api/admin/admin/users', payload)
export const updateUser = (user_id, payload) =>
  request(`/api/admin/admin/users/${user_id}`, { method: 'PATCH', body: JSON.stringify(payload) })

export const listAgents = () => request('/api/admin/admin/agents')
export const createAgent = (payload) => post('/api/admin/admin/agents', payload)
export const updateAgent = (employee_id, payload) =>
  request(`/api/admin/admin/agents/${employee_id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })