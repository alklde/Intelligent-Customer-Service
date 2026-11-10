<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAdminStatus, getStaffCaptcha, initAdmin, staffLogin } from '../api.js'
import { setAuth } from '../auth.js'

const router = useRouter()
const route = useRoute()

const employeeId = ref('')
const secret = ref('')
const captchaCode = ref('')
const captcha = ref(null)
const loading = ref(false)
const error = ref('')

const needInit = ref(false)
const initLoading = ref(false)
const notice = ref('')
const initForm = reactive({ employee_id: '', secret: '', name: '系统管理员', bootstrap_key: '' })

async function refreshCaptcha() {
  captchaCode.value = ''
  try {
    captcha.value = await getStaffCaptcha()
  } catch (e) {
    error.value = `验证码加载失败：${e.message}`
  }
}

async function submit() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const data = await staffLogin({
      employee_id: employeeId.value.trim(),
      secret: secret.value,
      captcha_id: captcha.value?.captcha_id || '',
      captcha_code: captchaCode.value.trim(),
    })
    setAuth(data)
    router.replace(route.query.redirect || '/staff/workbench')
  } catch (e) {
    error.value = e.message
    await refreshCaptcha()
  } finally {
    loading.value = false
  }
}

async function submitInit() {
  if (initLoading.value) return
  error.value = ''
  notice.value = ''
  initLoading.value = true
  try {
    await initAdmin({ ...initForm })
    notice.value = '管理员初始化成功，请使用刚设置的工号与密钥登录'
    needInit.value = false
    employeeId.value = initForm.employee_id
    initForm.secret = ''
    initForm.bootstrap_key = ''
    await refreshCaptcha()
  } catch (e) {
    error.value = e.message
  } finally {
    initLoading.value = false
  }
}

onMounted(async () => {
  await refreshCaptcha()
  try {
    const status = await getAdminStatus()
    needInit.value = Boolean(status.bootstrap_required)
  } catch {
    /* 状态接口暂不可用时按已初始化处理，登录时会给出明确错误 */
  }
})
</script>

<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="brand-mark" style="width: 52px; height: 52px; font-size: 19px">AI</div>
      <h1>客服工作台</h1>
      <p>人工坐席与管理员统一入口。工号即身份，接单、回复与工单归属全程可追溯。</p>
      <ul>
        <li>待接入队列实时抢占，AI 上下文随手可查</li>
        <li>工单管理：包裹单号 / 客户 / 接单客服</li>
        <li>管理员可进入数据库管理，维护账号体系</li>
      </ul>
      <div class="hero-hint">
        普通客户请前往
        <RouterLink to="/login">客户登录</RouterLink>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <!-- 首次部署：初始化管理员 -->
        <template v-if="needInit">
          <h2>初始化管理员</h2>
          <p class="auth-sub">系统尚未初始化，请先创建第一个管理员账号</p>

          <div v-if="error" class="error-banner" style="margin-bottom: 14px">{{ error }}</div>
          <div v-if="notice" class="notice-banner" style="margin-bottom: 14px">{{ notice }}</div>

          <label class="field">
            <span>管理员工号</span>
            <input v-model="initForm.employee_id" class="input" placeholder="例如 admin001" />
          </label>
          <label class="field">
            <span>登录密钥</span>
            <input v-model="initForm.secret" class="input" type="password" placeholder="至少 8 位" />
          </label>
          <label class="field">
            <span>姓名</span>
            <input v-model="initForm.name" class="input" />
          </label>
          <label class="field">
            <span>初始化引导密钥</span>
            <input v-model="initForm.bootstrap_key" class="input" placeholder="见 README / ADMIN_BOOTSTRAP_KEY" />
          </label>

          <button class="btn auth-submit" :disabled="initLoading || !initForm.employee_id || !initForm.secret || !initForm.bootstrap_key" @click="submitInit">
            <span v-if="initLoading" class="spin"></span> 创建管理员
          </button>
          <p class="auth-foot">初始化完成后即可使用该工号登录客服工作台</p>
        </template>

        <!-- 常规登录 -->
        <template v-else>
          <h2>客服登录</h2>
          <p class="auth-sub">使用工号与登录密钥</p>

          <div v-if="error" class="error-banner" style="margin-bottom: 14px">{{ error }}</div>
          <div v-if="notice" class="notice-banner" style="margin-bottom: 14px">{{ notice }}</div>

          <label class="field">
            <span>客服工号</span>
            <input v-model="employeeId" class="input" autocomplete="username" placeholder="例如 agent001" />
          </label>
          <label class="field">
            <span>登录密钥</span>
            <input v-model="secret" class="input" type="password" autocomplete="current-password" placeholder="至少 8 位" @keyup.enter="submit" />
          </label>
          <label class="field">
            <span>图形验证码</span>
            <div class="captcha-row">
              <input v-model="captchaCode" class="input" maxlength="8" placeholder="输入图中字符" @keyup.enter="submit" />
              <button type="button" class="captcha-img" title="点击刷新" @click="refreshCaptcha">
                <img v-if="captcha" :src="captcha.image" alt="验证码" />
                <span v-else class="spin"></span>
              </button>
            </div>
          </label>

          <button class="btn auth-submit" :disabled="loading || !employeeId || !secret || !captchaCode" @click="submit">
            <span v-if="loading" class="spin"></span> 登录
          </button>
          <p class="auth-foot">演示账号：agent001 / Agent@123456 · 管理员 admin001 / Admin@123456</p>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: flex; background: radial-gradient(circle at 82% 20%, rgba(76, 201, 240, 0.16), transparent 45%), var(--bg); }
.auth-hero { flex: 1; padding: 72px 64px; display: flex; flex-direction: column; justify-content: center; gap: 16px; max-width: 560px; }
.auth-hero h1 { font-size: 32px; letter-spacing: 1px; }
.auth-hero p { color: var(--text-dim); font-size: 15px; line-height: 1.8; }
.auth-hero ul { margin: 8px 0 0 18px; color: var(--text-dim); display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
.hero-hint { margin-top: 24px; font-size: 13px; color: var(--text-dim); }
.hero-hint a { color: var(--cyan); text-decoration: none; margin-left: 4px; }
.auth-panel { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px; }
.auth-card { width: 100%; max-width: 400px; background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 32px; }
.auth-card h2 { font-size: 22px; }
.auth-sub { color: var(--text-dim); font-size: 13px; margin: 6px 0 22px; }
.field { display: flex; flex-direction: column; gap: 7px; margin-bottom: 14px; }
.field span { font-size: 12px; color: var(--text-dim); }
.captcha-row { display: flex; gap: 10px; }
.captcha-img { width: 132px; height: 44px; flex-shrink: 0; border-radius: 9px; overflow: hidden; border: 1px solid var(--border-strong); background: var(--bg-soft); display: grid; place-items: center; cursor: pointer; padding: 0; }
.captcha-img img { width: 100%; height: 100%; display: block; }
.auth-submit { width: 100%; margin-top: 8px; }
.auth-foot { text-align: center; color: var(--text-dim); font-size: 12px; margin-top: 16px; line-height: 1.7; }
.notice-banner { background: rgba(61, 214, 140, 0.10); border: 1px solid rgba(61, 214, 140, 0.35); color: var(--ok); padding: 10px 14px; border-radius: 9px; font-size: 13px; }
</style>