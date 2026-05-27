/**
 * i18n 键值对齐验证脚本
 * 用法: npx tsx scripts/check-i18n.ts
 * 检查所有语言文件的 section 及叶子键是否与 zh.ts 对齐
 */
import { existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

type LocaleData = Record<string, unknown>

const LOCALES = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es'] as const
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const I18N_DIR = resolve(__dirname, '../src/i18n')

async function loadLocale(locale: string): Promise<LocaleData | null> {
  const filepath = resolve(I18N_DIR, `${locale}.ts`)
  if (!existsSync(filepath)) {
    console.error(`[MISSING] ${filepath} — file does not exist`)
    return null
  }
  try {
    const mod = await import(filepath)
    return (mod.default || mod) as LocaleData
  } catch (e) {
    console.error(`[ERROR] Failed to load ${filepath}:`, (e as Error).message)
    return null
  }
}

function collectLeafPaths(obj: unknown, prefix = ''): string[] {
  if (typeof obj !== 'object' || obj === null) return []
  const record = obj as Record<string, unknown>
  const paths: string[] = []
  for (const key of Object.keys(record)) {
    const full = prefix ? `${prefix}.${key}` : key
    const val = record[key]
    if (typeof val === 'object' && val !== null) {
      paths.push(...collectLeafPaths(val, full))
    } else {
      paths.push(full)
    }
  }
  return paths
}

async function main() {
  const data: Record<string, LocaleData | null> = {}
  for (const loc of LOCALES) {
    data[loc] = await loadLocale(loc)
  }

  const zhData = data['zh']
  if (!zhData) {
    console.error('[FATAL] Cannot load zh.ts — aborting')
    process.exit(1)
  }

  const zhSections = Object.keys(zhData)
  const zhLeaves = new Set(collectLeafPaths(zhData))

  let totalMissing = 0

  for (const loc of LOCALES) {
    if (loc === 'zh') continue
    const locData = data[loc]
    if (!locData) continue

    const locSections = Object.keys(locData)

    // 缺失的 section
    const missingSections = zhSections.filter(s => !locSections.includes(s))
    if (missingSections.length > 0) {
      console.log(`\n[${loc}] 缺失 section (${missingSections.length}):`)
      for (const s of missingSections) {
        console.log(`  - ${s}  (用户将看到中文回退)`)
      }
      totalMissing += missingSections.length
    }

    // 缺失的叶子键（仅在共享 section 内检查）
    for (const section of zhSections) {
      if (!locSections.includes(section)) continue
      const zhSectionLeaves = collectLeafPaths(zhData[section], section)
      const locSectionLeaves = new Set(collectLeafPaths(locData[section], section))
      const missingLeaves = zhSectionLeaves.filter(l => !locSectionLeaves.has(l))
      if (missingLeaves.length > 0) {
        console.log(`\n[${loc}] ${section} 缺失键 (${missingLeaves.length}):`)
        for (const k of missingLeaves.slice(0, 20)) {
          console.log(`  - ${k}`)
        }
        if (missingLeaves.length > 20) {
          console.log(`  ... 及其他 ${missingLeaves.length - 20} 个键`)
        }
        totalMissing += missingLeaves.length
      }
    }
  }

  console.log(`\n===== 汇总 =====`)
  console.log(`zh 总键数: ${zhLeaves.size}`)
  for (const loc of LOCALES) {
    if (loc === 'zh') continue
    const locData = data[loc]
    if (!locData) continue
    const locLeaves = collectLeafPaths(locData)
    const coverage = zhLeaves.size > 0 ? ((locLeaves.length / zhLeaves.size) * 100).toFixed(1) : '0'
    console.log(`${loc}: ${locLeaves.length} 键 (覆盖率 ${coverage}%)`)
  }
  console.log(`总缺失: ${totalMissing}`)

  if (totalMissing > 0) {
    console.log(`\n[FAIL] 存在 ${totalMissing} 处缺失，语言切换时将回退到中文`)
    process.exit(1)
  } else {
    console.log('\n[PASS] 所有语言文件键值对齐')
  }
}

main()
