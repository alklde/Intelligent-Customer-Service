/** 登录态存储与角色判定。
 *
 * 令牌与身份保存在 sessionStorage：仅当前标签页有效，刷新保持登录，
 * 新开标签页需重新登录，多标签页互不影响（并行、互不覆盖）。
 */
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'suite_auth'

const state = reactive({ token: '', role: '', subject: '', name: '' })

// 清理旧版本跨标签共享的登录态，确保新标签页从登录页开始
localStorage.removeItem(STORAGE_KEY)

const raw = sessionStorage.getItem(STORAGE_KEY)
if (raw) {
  try {
    Object.assign(state, JSON.parse(raw))
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
  }
}

export const auth = state

export const isLoggedIn = computed(() => Boolean(state.token))
export const isCustomer = computed(() => state.role === 'customer')
export const isStaff = computed(() => state.role === 'agent' || state.role === 'admin')
export const isAdmin = computed(() => state.role === 'admin')

export function setAuth(data) {
  Object.assign(state, {
    token: data.token,
    role: data.role,
    subject: data.subject,
    name: data.name,
  })
  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ token: state.token, role: state.role, subject: state.subject, name: state.name }),
  )
}

export function clearAuth() {
  state.token = ''
  state.role = ''
  state.subject = ''
  state.name = ''
  sessionStorage.removeItem(STORAGE_KEY)
}

export function getToken() {
  return state.token
}

/** 已登录用户的默认落地页；未登录返回客户登录页。 */
export function homePath() {
  if (state.role === 'customer') return '/service'
  if (state.role === 'agent' || state.role === 'admin') return '/staff/workbench'
  return '/login'
}