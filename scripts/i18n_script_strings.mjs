#!/usr/bin/env node
// i18n_script_strings.mjs — Phase-2: ElMessage.*('...' | "...") 含中文 → t('key')
// 仅单参数闭括号形式： ElMessage.success('x')  （不含逗号第二参数；不含反引号）
// 结束后执行: pnpm i18n:sync
//
//   pnpm i18n:script-strings
//   pnpm i18n:script-strings -- --apply
//   pnpm i18n:script-strings -- --apply --files src/components/ChatMessage.vue,src/stores/chat.ts

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'vue/compiler-sfc'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const ZH = path.join(ROOT, 'src', 'i18n', 'zh.ts')
const PLAN = path.join(__dirname, 'i18n_script_strings.plan.json')

const HAN = /[\u4e00-\u9fff]/

// Single-arg only, closing paren — ElMessage.success('...') 最保守
const RE_TRIVIAL_SQ = /ElMessage\.(success|error|warning|info)\(\s*'((?:\\.|[^'\\])*)'\s*\)/g
const RE_TRIVIAL_DQ = /ElMessage\.(success|error|warning|info)\(\s*"((?:\\.|[^"\\])*)"\s*\)/g

function parseArgs(argv) {
  const a = { apply: false, files: null }
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--apply') a.apply = true
    else if (argv[i] === '--files' && argv[i + 1]) a.files = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
  }
  return a
}

function fileSlug(filePath) {
  const base = path.basename(filePath, path.extname(filePath))
  return base.charAt(0).toLowerCase() + base.slice(1)
}

function unescapeStr(s) {
  return s
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, '\\')
}

async function walkDir(dir) {
  const out = []
  const ents = await fs.readdir(dir, { withFileTypes: true })
  for (const e of ents) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'i18n' || e.name === 'node_modules') continue
      out.push(...(await walkDir(full)))
    } else if (e.name.endsWith('.vue')) {
      out.push(full)
    }
  }
  return out
}

async function walkTsStores() {
  const p = path.join(SRC, 'stores')
  try {
    const ents = await fs.readdir(p, { withFileTypes: true })
    return ents.filter((e) => e.isFile() && e.name.endsWith('.ts')).map((e) => path.join(p, e.name))
  } catch {
    return []
  }
}

function findTrivialInText(script) {
  const hits = []
  for (const re of [RE_TRIVIAL_SQ, RE_TRIVIAL_DQ]) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(script)) !== null) {
      const full = m[0]
      const method = m[1]
      const rawInner = m[2]
      const inner = unescapeStr(rawInner)
      if (!HAN.test(inner)) continue
      hits.push({ full, method, cn: inner, key: null })
    }
  }
  return hits
}

function transformScriptContent(script, slug, nStart = 0) {
  const hits = findTrivialInText(script)
  if (!hits.length) return { out: script, keys: [], nEnd: nStart }
  // De-dupe `full` call text (repeated identical toasts share one i18n key)
  const seen = new Set()
  const list = []
  for (const h of hits) {
    if (seen.has(h.full)) continue
    seen.add(h.full)
    list.push(h)
  }
  let n = nStart
  const keys = []
  let out = script
  for (const h of list) {
    n += 1
    const key = `${slug}.elMessage_${n}`
    keys.push({ key, cn: h.cn })
    const newCall = `ElMessage.${h.method}(t('${key}'))`
    out = out.split(h.full).join(newCall)
  }
  return { out, keys, nEnd: n }
}

function ensureI18nInBlock(block, needsT) {
  if (!needsT) return block
  const hasImport = /from\s+['"]vue-i18n['"]/.test(block)
  const hasT = /const\s*{\s*t\s*}\s*=\s*useI18n/.test(block) || /useI18n\s*\(\s*\)/.test(block)
  let b = block
  if (!hasImport) {
    // Insert *after* the last complete `... from 'pkg'` line (multiline `import {` safe).
    const lines = b.split('\n')
    let lastFrom = -1
    for (let i = 0; i < lines.length; i++) {
      if (/from\s+['"][^'"]*['"]\s*;?\s*$/.test(lines[i].trim())) lastFrom = i
    }
    if (lastFrom >= 0) {
      lines.splice(lastFrom + 1, 0, "import { useI18n } from 'vue-i18n'")
      b = lines.join('\n')
    } else {
      b = "import { useI18n } from 'vue-i18n'\n" + b
    }
  }
  if (!hasT) {
    const afterImports = b.split('\n')
    let insertAt = 0
    for (let i = 0; i < afterImports.length; i++) {
      if (/^import\s/.test(afterImports[i].trim())) insertAt = i + 1
    }
    afterImports.splice(insertAt, 0, '', 'const { t } = useI18n()')
    b = afterImports.join('\n')
  }
  return b
}

async function processVueFile(absPath) {
  const rel = path.relative(ROOT, absPath)
  const src = await fs.readFile(absPath, 'utf8')
  const slug = fileSlug(absPath)
  const { descriptor, errors } = parse(src, { filename: absPath })
  if (errors && errors.length) {
    return { rel, error: 'SFC parse errors', count: 0 }
  }
  const parts = [descriptor.scriptSetup, descriptor.script].filter(Boolean)
  if (!parts.length) return { rel, count: 0, allKeys: [] }

  /// Ascending in file: offset-merged rewrite after each block.
  parts.sort((a, b) => a.loc.start.offset - b.loc.start.offset)
  let newSrc = src
  const allKeys = []
  let n0 = 0
  let offsetShift = 0
  for (const b of parts) {
    const { out: tr, keys, nEnd } = transformScriptContent(b.content, slug, n0)
    n0 = nEnd
    if (!keys.length) continue
    const withI18n = ensureI18nInBlock(tr, true)
    allKeys.push(...keys)
    const start = b.loc.start.offset + offsetShift
    const end = b.loc.end.offset + offsetShift
    newSrc = newSrc.slice(0, start) + withI18n + newSrc.slice(end)
    offsetShift += withI18n.length - (b.loc.end.offset - b.loc.start.offset)
  }
  if (!allKeys.length) return { rel, count: 0, allKeys: [] }

  return { rel, newSrc, allKeys, count: allKeys.length }
}

async function processTsFile(absPath) {
  const rel = path.relative(ROOT, absPath)
  const src = await fs.readFile(absPath, 'utf8')
  const slug = fileSlug(absPath) // e.g. chat → chat
  const { out, keys: allKeys } = transformScriptContent(src, slug)
  if (!allKeys.length) return { rel, count: 0, allKeys: [] }
  const withI18n = ensureI18nInBlock(out, true)
  return { rel, newSrc: withI18n, allKeys, count: allKeys.length }
}

/* zh.ts — same pattern as i18n_sync / extract */
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

function serializeObj(obj, indent = 0) {
  const pad = '  '.repeat(indent)
  const inner = '  '.repeat(indent + 1)
  const lines = ['{']
  const entries = Object.entries(obj)
  entries.forEach(([k, v], i) => {
    const keyStr = /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k) ? k : JSON.stringify(k)
    let valStr
    if (v && typeof v === 'object' && !Array.isArray(v)) valStr = serializeObj(v, indent + 1)
    else if (Array.isArray(v)) valStr = JSON.stringify(v)
    else valStr = JSON.stringify(v)
    const comma = i < entries.length - 1 ? ',' : ','
    lines.push(`${inner}${keyStr}: ${valStr}${comma}`)
  })
  lines.push(`${pad}}`)
  return lines.join('\n')
}

async function loadZh() {
  const text = await fs.readFile(ZH, 'utf8')
  const idx = text.indexOf('export default')
  const header = idx > 0 ? text.slice(0, idx) : ''
  const body = (idx >= 0 ? text.slice(idx) : text).replace(/^export\s+default\s+/, '').trim().replace(/;?\s*$/, '')
  const dict = new Function(`return (${body})`)() // eslint-disable-line no-new-func
  return { header, dict }
}

async function main() {
  const args = parseArgs(process.argv)
  let vfiles = await walkDir(SRC)
  vfiles = vfiles.filter((f) => !f.includes('node_modules'))
  const tfiles = await walkTsStores()
  let files = [...vfiles, ...tfiles]
  if (args.files) {
    files = args.files.map((f) => (path.isAbsolute(f) ? f : path.join(ROOT, f)))
  }

  const plan = []
  for (const f of files) {
    if (f.endsWith('.ts')) {
      const r = await processTsFile(f)
      if (r.count) plan.push(r)
    } else {
      const r = await processVueFile(f)
      if (r.error) {
        console.warn(`[script-strings] skip ${r.rel}: ${r.error}`)
        continue
      }
      if (r.count) plan.push(r)
    }
  }

  const total = plan.reduce((a, p) => a + p.count, 0)
  console.log(`[script-strings] files with trivial ElMessage(...): ${plan.length} replacements: ${total}`)
  plan.forEach((p) => console.log(`  ${p.rel.padEnd(60)} ${p.count}`))
  await fs.writeFile(PLAN, JSON.stringify(plan, null, 2), 'utf8')
  console.log(`[script-strings] plan → ${path.relative(ROOT, PLAN)}`)

  if (!args.apply) {
    console.log(`[script-strings] dry run — add --apply to write sources + zh.ts`)
    return
  }

  const zh = await loadZh()
  for (const p of plan) {
    if (!p.newSrc) continue
    await fs.writeFile(path.join(ROOT, p.rel), p.newSrc, 'utf8')
    const kslug = fileSlug(p.rel)
    for (const { key, cn } of p.allKeys) {
      setDeep(zh.dict, key, cn)
    }
    console.log(`  wrote ${p.rel} + ${p.allKeys.length} keys (under ${kslug}.*)`) 
  }
  const out = `${zh.header}export default ${serializeObj(zh.dict)}\n`
  await fs.writeFile(ZH, out, 'utf8')
  console.log(`[script-strings] done. Run: pnpm i18n:sync`)
}

main().catch((e) => {
  console.error('[script-strings] fatal:', e.message)
  process.exit(1)
})
