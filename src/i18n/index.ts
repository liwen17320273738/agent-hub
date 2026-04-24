import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'
import ja from './ja'
import ko from './ko'
import fr from './fr'
import de from './de'
import es from './es'

export const SUPPORTED_LOCALES = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es'] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export const LOCALE_LABEL: Record<AppLocale, string> = {
  zh: '中文',
  en: 'English',
  ja: '日本語',
  ko: '한국어',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
}

/** BCP-47 tag for `Intl` / `toLocaleString` from app locale code. */
const BCP47: Record<AppLocale, string> = {
  zh: 'zh-CN',
  en: 'en-US',
  ja: 'ja-JP',
  ko: 'ko-KR',
  fr: 'fr-FR',
  de: 'de-DE',
  es: 'es-ES',
}

export function appLocaleToBcp47(loc: AppLocale | string | undefined | null): string {
  if (loc && (SUPPORTED_LOCALES as readonly string[]).includes(loc)) {
    return BCP47[loc as AppLocale] ?? 'en-US'
  }
  return 'en-US'
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
  if (lc.startsWith('fr')) return 'fr'
  if (lc.startsWith('de')) return 'de'
  if (lc.startsWith('es')) return 'es'
  if (lc.startsWith('en')) return 'en'
  return 'zh'
}

const savedLocale = normalizeLocale(
  typeof localStorage !== 'undefined' ? localStorage.getItem('agent-hub-locale') : null,
)

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  // UI copy lives in this repo (versioned, fast) — not from DB. `fallbackLocale` only helps when a key
  // is missing in the active catalog; `pnpm i18n:audit` + zh-first workflow keeps that rare.
  fallbackLocale: ['en', 'zh'],
  messages: { zh, en, ja, ko, fr, de, es },
  // After audit passes, missing keys should be ~0; keep dev warnings, silence production console noise.
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
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
