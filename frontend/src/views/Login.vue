<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCustomerCaptcha, customerLogin } from '../api.js'
import { setAuth } from '../auth.js'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const captchaCode = ref('')
const captcha = ref(null)
const loading = ref(false)
const error = ref('')

async function refreshCaptcha() {
  captchaCode.value = ''
  try {
    captcha.value = await getCustomerCaptcha()
  } catch (e) {
    error.value = `验证码加载失败：${e.message}`
  }
}

async function submit() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const data = await customerLogin({
      username: username.value.trim(),
      password: password.value,
      captcha_id: captcha.value?.captcha_id || '',
      captcha_code: captchaCode.value.trim(),
    })
    setAuth(data)
    router.replace(route.query.redirect || '/service')
  } catch (e) {
    error.value = e.message
    await refreshCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(refreshCaptcha)
</script>

<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="brand-mark" style="width: 52px; height: 52px; font-size: 19px">AI</div>
      <h1>客户服务门户</h1>
      <p>智能客服 7×24 小时在线，复杂问题无缝转接人工坐席。</p>
      <ul>
        <li>智能应答，常见售后问题快速解决</li>
        <li>AI 与人工客服同一会话无缝切换</li>
        <li>申请单全程可查：包裹单号 / 接单客服</li>
      </ul>
      <div class="hero-hint">
        客服人员请前往
        <RouterLink to="/staff/login">客服登录</RouterLink>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <h2>客户登录</h2>
        <p class="auth-sub">使用你的账号密码登录</p>

        <div v-if="error" class="error-banner" style="margin-bottom: 14px">{{ error }}</div>

        <label class="field">
          <span>用户名</span>
          <input v-model="username" class="input" autocomplete="username" placeholder="例如 zhangsan" />
        </label>
        <label class="field">
          <span>密码</span>
          <input v-model="password" class="input" type="password" autocomplete="current-password" placeholder="至少 6 位" @keyup.enter="submit" />
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

        <button class="btn auth-submit" :disabled="loading || !username || !password || !captchaCode" @click="submit">
          <span v-if="loading" class="spin"></span> 登录
        </button>
        <p class="auth-foot">演示账号：zhangsan / 123456</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: flex; background: radial-gradient(circle at 18% 20%, rgba(124, 108, 255, 0.18), transparent 45%), var(--bg); }
.auth-hero { flex: 1; padding: 72px 64px; display: flex; flex-direction: column; justify-content: center; gap: 16px; max-width: 560px; }
.auth-hero h1 { font-size: 32px; letter-spacing: 1px; }
.auth-hero p { color: var(--text-dim); font-size: 15px; line-height: 1.8; }
.auth-hero ul { margin: 8px 0 0 18px; color: var(--text-dim); display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
.hero-hint { margin-top: 24px; font-size: 13px; color: var(--text-dim); }
.hero-hint a { color: var(--accent); text-decoration: none; margin-left: 4px; }
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
.auth-foot { text-align: center; color: var(--text-dim); font-size: 12px; margin-top: 16px; }
</style>