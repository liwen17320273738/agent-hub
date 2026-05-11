import { createApp } from 'vue'
import { createPinia } from 'pinia'
// Element Plus: on-demand import via unplugin-vue-components + unplugin-auto-import
// CSS is auto-imported per component by the Vite plugin resolver
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './styles/main.css'
import { isEnterpriseBuild } from './services/enterpriseApi'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

// ── Global error handler ──────────────────────────────────────────
// Catches unhandled errors from any component lifecycle / event handler.
// Prevents full app white-screen; logs to console for debugging.
app.config.errorHandler = (err, _instance, info) => {
  const msg = err instanceof Error ? err.message : String(err)
  console.error(`[GlobalErrorHandler] ${info}:`, err)
  // Brief notification — uses ElMessage via auto-import
  try {
    ElMessage.error({ message: `渲染错误: ${msg}`, duration: 5000 })
  } catch {
    alert(`渲染错误: ${msg}`)
  }
}
// No app.use(ElementPlus) — components are auto-imported on demand

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

;(async () => {
  if (isEnterpriseBuild) {
    await useAuthStore().hydrate()
  }
  app.mount('#app')
})()
