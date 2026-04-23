import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

const savedLocale = localStorage.getItem('agent-hub-locale') || 'zh'

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'zh',
  messages: { zh, en },
})

export function setLocale(locale: 'zh' | 'en') {
  ;(i18n.global.locale as any).value = locale
  localStorage.setItem('agent-hub-locale', locale)
}

export function getLocale(): string {
  return (i18n.global.locale as any).value
}

export default i18n
