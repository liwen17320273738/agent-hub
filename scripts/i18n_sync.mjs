#!/usr/bin/env node
// i18n_sync.mjs — auto-fill missing translation keys using an LLM.
//
// Single source of truth: src/i18n/zh.ts.
// For every target locale (en/ja/ko), we find keys that exist in zh but not
// in the target, batch them, ask an OpenAI-compatible model to translate,
// and splice the results back into the target file.
//
// Usage
//   OPENAI_API_KEY=sk-... node scripts/i18n_sync.mjs
//   OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.deepseek.com/v1 I18N_MODEL=deepseek-chat node scripts/i18n_sync.mjs
//   node scripts/i18n_sync.mjs --dry-run                        # preview only
//   node scripts/i18n_sync.mjs --locales en,ja                  # restrict targets
//   node scripts/i18n_sync.mjs --force                          # retranslate even keys that exist
//
// Design notes
//   * Nested object shape in *.ts is preserved — we re-serialize to TS so `git
//     diff` only shows new keys (no reordering churn) when keys are appended.
//   * We translate in one batch per locale to amortize prompt overhead.
//   * Placeholders like {n}, {stage}, {label} and inline HTML (<code>/<strong>)
//     are preserved by the prompt.
//   * Quotes in translations are escaped via JSON.stringify, so the generated
//     TS is always syntactically valid.

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const I18N_DIR = path.join(ROOT, 'src', 'i18n')
const SOURCE = 'zh'
const DEFAULT_TARGETS = ['en', 'ja', 'ko']

const LANG_NAME = {
  en: 'English (en)',
  ja: 'Japanese (日本語, ja)',
  ko: 'Korean (한국어, ko)',
  fr: 'French (Français, fr)',
  de: 'German (Deutsch, de)',
  es: 'Spanish (Español, es)',
  pt: 'Portuguese (Português, pt)',
  ru: 'Russian (Русский, ru)',
  it: 'Italian (Italiano, it)',
  vi: 'Vietnamese (Tiếng Việt, vi)',
  th: 'Thai (ไทย, th)',
  id: 'Indonesian (Bahasa Indonesia, id)',
}

function parseArgs(argv) {
  const args = { dryRun: false, force: false, locales: null, limit: 0 }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--dry-run' || a === '-n') args.dryRun = true
    else if (a === '--force' || a === '-f') args.force = true
    else if (a === '--locales' && argv[i + 1]) args.locales = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
    else if (a === '--limit' && argv[i + 1]) args.limit = parseInt(argv[++i], 10) || 0
    else if (a === '--help' || a === '-h') {
      console.log('Usage: node scripts/i18n_sync.mjs [--dry-run] [--force] [--locales en,ja] [--limit N]')
      process.exit(0)
    }
  }
  return args
}

/**
 * Loads a *.ts locale file as a plain JS object. The files are pure data
 * (`export default { ... }`) so we can strip the prefix and eval the literal
 * in a Function scope. Comments at top (//) are preserved separately.
 */
async function loadLocale(locale) {
  const file = path.join(I18N_DIR, `${locale}.ts`)
  let text
  try {
    text = await fs.readFile(file, 'utf8')
  } catch (e) {
    if (e.code === 'ENOENT') return { header: '', dict: {} }
    throw e
  }
  const idx = text.indexOf('export default')
  const header = idx > 0 ? text.slice(0, idx) : ''
  const body = (idx >= 0 ? text.slice(idx) : text).replace(/^export\s+default\s+/, '').trim().replace(/;?\s*$/, '')
  // eslint-disable-next-line no-new-func
  const dict = new Function(`return (${body})`)()
  return { header, dict }
}

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out)
    else out[key] = v
  }
  return out
}

function setDeep(obj, dottedKey, value) {
  const parts = dottedKey.split('.')
  let cur = obj
  for (let i = 0; i < parts.length - 1; i++) {
    const p = parts[i]
    if (!cur[p] || typeof cur[p] !== 'object' || Array.isArray(cur[p])) cur[p] = {}
    cur = cur[p]
  }
  cur[parts[parts.length - 1]] = value
}

/**
 * Serializes a JS object back to a valid TS `export default { ... }` source.
 * Keys are rendered unquoted when they are plain identifiers (keeps the diff
 * tight vs. the human-authored original style).
 */
function serialize(obj, indent = 0) {
  const pad = '  '.repeat(indent)
  const inner = '  '.repeat(indent + 1)
  const lines = ['{']
  const entries = Object.entries(obj)
  entries.forEach(([k, v], i) => {
    const keyStr = /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k) ? k : JSON.stringify(k)
    let valStr
    if (v && typeof v === 'object' && !Array.isArray(v)) valStr = serialize(v, indent + 1)
    else if (Array.isArray(v)) valStr = JSON.stringify(v)
    else valStr = JSON.stringify(v)
    const comma = i < entries.length - 1 ? ',' : ','
    lines.push(`${inner}${keyStr}: ${valStr}${comma}`)
  })
  lines.push(`${pad}}`)
  return lines.join('\n')
}

async function translateBatch(entries, targetLocale) {
  if (!entries || Object.keys(entries).length === 0) return {}
  const apiKey = process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY
  const apiUrl = (process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\/$/, '')
  const model = process.env.I18N_MODEL || 'gpt-4o-mini'
  if (!apiKey) throw new Error('OPENAI_API_KEY (or ANTHROPIC_API_KEY) required. For a dry preview use --dry-run.')

  const langName = LANG_NAME[targetLocale] || targetLocale
  const sys = [
    `You are a professional UI translator for an enterprise AI product called "Agent Hub".`,
    `Translate Chinese UI strings into ${langName}.`,
    `Rules:`,
    `  1) Preserve ALL placeholders exactly: {n}, {stage}, {label}, {avg}, {from}, {to}, {v}, {s}, etc.`,
    `  2) Preserve inline HTML tags exactly: <code>…</code>, <strong>…</strong>.`,
    `  3) Keep technical terms recognisable: Agent, DAG, RBAC, MCP, SKILL.md, pipeline, gate, workflow.`,
    `  4) Prefer short, concise UI copy. No explanations. No quotes around output.`,
    `  5) Output STRICT JSON: one object mapping the input key to the translated string. Nothing else.`,
  ].join('\n')

  const user = `Translate each value to ${langName}. Output ONLY a JSON object of the same keys.\n\nINPUT:\n${JSON.stringify(entries, null, 2)}`

  const url = `${apiUrl}/chat/completions`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      temperature: 0,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: sys },
        { role: 'user', content: user },
      ],
    }),
  })
  if (!res.ok) {
    const errTxt = await res.text()
    throw new Error(`LLM ${res.status}: ${errTxt.slice(0, 400)}`)
  }
  const data = await res.json()
  const content = data?.choices?.[0]?.message?.content || '{}'
  if (process.env.I18N_DEBUG) console.log(`[${targetLocale}] raw LLM response (first 500 chars):`, content.slice(0, 500))
  try {
    return JSON.parse(content)
  } catch {
    // Some models wrap JSON in ```json fences; strip and retry once.
    const m = content.match(/```(?:json)?\s*([\s\S]*?)```/)
    if (m) return JSON.parse(m[1])
    throw new Error(`Model did not return JSON: ${content.slice(0, 200)}`)
  }
}

async function main() {
  const args = parseArgs(process.argv)
  const targets = args.locales || DEFAULT_TARGETS

  const src = await loadLocale(SOURCE)
  const flatSrc = flatten(src.dict)

  console.log(`[i18n] source=${SOURCE} keys=${Object.keys(flatSrc).length}`)
  console.log(`[i18n] targets=${targets.join(', ')}`)
  if (args.dryRun) console.log('[i18n] DRY RUN — no files will be written, no API calls will be made')

  for (const tgt of targets) {
    if (tgt === SOURCE) continue
    const target = await loadLocale(tgt)
    const flatTgt = flatten(target.dict)
    const needed = {}
    for (const k of Object.keys(flatSrc)) {
      if (args.force || !(k in flatTgt)) needed[k] = flatSrc[k]
    }
    const keys = Object.keys(needed)
    const slice = args.limit > 0 ? keys.slice(0, args.limit) : keys
    console.log(`\n[${tgt}] missing=${keys.length}${slice.length !== keys.length ? ` (translating first ${slice.length})` : ''}`)

    if (!slice.length) {
      console.log(`[${tgt}] already complete`)
      continue
    }
    if (args.dryRun) {
      console.log(`[${tgt}] would translate keys:`, slice.slice(0, 15).join(', '), slice.length > 15 ? `…(+${slice.length - 15})` : '')
      continue
    }

    // Batch to keep prompts under ~8k chars and let the model stay accurate.
    const BATCH_SIZE = parseInt(process.env.I18N_BATCH_SIZE || '40', 10)
    let applied = 0
    for (let off = 0; off < slice.length; off += BATCH_SIZE) {
      const chunk = slice.slice(off, off + BATCH_SIZE)
      const batch = {}
      for (const k of chunk) batch[k] = needed[k]
      process.stdout.write(`[${tgt}] batch ${Math.floor(off / BATCH_SIZE) + 1}/${Math.ceil(slice.length / BATCH_SIZE)} (${chunk.length} keys)…`)
      const translated = await translateBatch(batch, tgt)
      let got = 0
      for (const [k, v] of Object.entries(translated)) {
        if (typeof v !== 'string' || !v.trim()) continue
        if (!(k in batch)) continue
        setDeep(target.dict, k, v)
        got += 1
        applied += 1
      }
      console.log(` ok ${got}/${chunk.length}`)
    }
    console.log(`[${tgt}] translated ${applied}/${slice.length}`)

    const header = target.header || `// ${tgt.toUpperCase()} locale — auto-synced from zh.ts via scripts/i18n_sync.mjs\n// Hand edits are fine; run the sync again to pick up new keys only.\n\n`
    const out = `${header}export default ${serialize(target.dict)}\n`
    await fs.writeFile(path.join(I18N_DIR, `${tgt}.ts`), out, 'utf8')
    console.log(`[${tgt}] wrote src/i18n/${tgt}.ts`)
  }

  console.log('\n[i18n] done.')
}

main().catch((e) => {
  console.error('[i18n] fatal:', e.message)
  process.exit(1)
})
