import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

const KNOWN_LOCALES = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es'] as const
type KnownLocale = (typeof KNOWN_LOCALES)[number]

const LOCALE_LABEL: Record<KnownLocale, string> = {
  zh: '中文',
  en: 'English',
  ja: '日本語',
  ko: '한국어',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
}

const BCP47: Record<KnownLocale, string> = {
  zh: 'zh-CN',
  en: 'en-US',
  ja: 'ja-JP',
  ko: 'ko-KR',
  fr: 'fr-FR',
  de: 'de-DE',
  es: 'es-ES',
}

export const SUPPORTED_LOCALES: readonly KnownLocale[] = KNOWN_LOCALES

export type AppLocale = KnownLocale

/** Static import map for lazy-loaded locale files. */
const LOCALE_IMPORTS: Record<string, () => Promise<{ default: Record<string, unknown> }>> = {
  ja: () => import('./ja'),
  ko: () => import('./ko'),
}

async function loadLocale(locale: string): Promise<void> {
  if (i18n.global.availableLocales.includes(locale)) return
  const loader = LOCALE_IMPORTS[locale]
  if (!loader) {
    console.warn(`[i18n] locale "${locale}" has no import entry, falling back to zh`)
    return
  }
  try {
    const messages = await loader()
    i18n.global.setLocaleMessage(locale, messages.default)
  } catch {
    console.warn(`[i18n] failed to load locale "${locale}", falling back to zh`)
  }
}

export function appLocaleToBcp47(loc: AppLocale | string | undefined | null): string {
  if (loc && (KNOWN_LOCALES as readonly string[]).includes(loc)) {
    return BCP47[loc as KnownLocale] ?? 'en-US'
  }
  return 'en-US'
}

function normalizeLocale(v: string | null): KnownLocale {
  if (v && (KNOWN_LOCALES as readonly string[]).includes(v)) {
    return v as KnownLocale
  }
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
  fallbackLocale: 'zh',
  messages: {
    zh,
    en,
    fr: en,
    de: en,
    es: en,
  },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
})

// Preload saved locale if it's not zh
if (savedLocale !== 'zh') {
  loadLocale(savedLocale)
}

export function setLocale(locale: AppLocale) {
  loadLocale(locale).then(() => {
    ;(i18n.global.locale as any).value = locale
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('agent-hub-locale', locale)
    }
  })
}

export function getLocale(): AppLocale {
  return (i18n.global.locale as any).value as AppLocale
}

export { LOCALE_LABEL }

export default i18n
