import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
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

app.config.errorHandler = (err, _instance, info) => {
  const msg = err instanceof Error ? err.message : String(err)
  console.error(`[GlobalErrorHandler] ${info}:`, err)
  try {
    ElMessage.error({ message: `渲染错误: ${msg}`, duration: 5000 })
  } catch {
    alert(`渲染错误: ${msg}`)
  }
}

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

;(async () => {
  if (isEnterpriseBuild) {
    await useAuthStore().hydrate()
  }
  app.mount('#app')
  // 同步 html lang 属性
  const i18n2 = app.config.globalProperties.$i18n
  if (i18n2) {
    watch(() => i18n2.locale, (l: string) => {
      document.documentElement.lang = l === 'zh' ? 'zh-CN' : l === 'en' ? 'en' : l
    }, { immediate: true })
  }
})()
