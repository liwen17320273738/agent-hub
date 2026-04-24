import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'
import ja from './ja'
import ko from './ko'

export const SUPPORTED_LOCALES = ['zh', 'en', 'ja', 'ko'] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export const LOCALE_LABEL: Record<AppLocale, string> = {
  zh: '中文',
  en: 'English',
  ja: '日本語',
  ko: '한국어',
}

function normalizeLocale(v: string | null): AppLocale {
  if (v && (SUPPORTED_LOCALES as readonly string[]).includes(v)) {
    return v as AppLocale
  }
  // Best-effort fallback from the browser's preferred language
  const nav = (typeof navigator !== 'undefined' ? navigator.language : '') || ''
  const lc = nav.toLowerCase()
  if (lc.startsWith('ja')) return 'ja'
  if (lc.startsWith('ko')) return 'ko'
  if (lc.startsWith('en')) return 'en'
  return 'zh'
}

const savedLocale = normalizeLocale(
  typeof localStorage !== 'undefined' ? localStorage.getItem('agent-hub-locale') : null,
)

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: ['en', 'zh'],
  messages: { zh, en, ja, ko },
})

export function setLocale(locale: AppLocale) {
  ;(i18n.global.locale as any).value = locale
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('agent-hub-locale', locale)
  }
}

export function getLocale(): AppLocale {
  return (i18n.global.locale as any).value as AppLocale
}

export default i18n
