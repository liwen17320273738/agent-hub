<template>
  <div class="login-page">
    <div class="login-card">
      <h1>Agent Hub</h1>
      <p class="subtitle">企业账号登录 · 组织共享会话与统一模型网关</p>
      <el-form :model="form" @submit.prevent="onSubmit" label-position="top" class="login-form">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" autocomplete="username" placeholder="name@company.com" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            show-password
            placeholder="密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" class="submit-btn" :loading="loading" native-type="submit">
          登录
        </el-button>
      </el-form>
      <p v-if="error" class="error-text">{{ error }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const form = reactive({ email: '', password: '' })
const loading = ref(false)
const error = ref('')

async function onSubmit() {
  error.value = ''
  if (!form.email.trim() || !form.password) {
    error.value = '请输入邮箱与密码'
    return
  }
  loading.value = true
  try {
    await auth.login(form.email.trim(), form.password)
    let redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    if (!redirect.startsWith('/') || redirect.startsWith('//')) redirect = '/'
    await router.replace(redirect)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px 36px;
  border-radius: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
}

.login-card h1 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.subtitle {
  margin: 0 0 28px;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
}

.login-form :deep(.el-form-item__label) {
  color: var(--text-secondary);
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
}

.error-text {
  margin: 16px 0 0;
  font-size: 13px;
  color: var(--el-color-danger);
}
</style>
