#!/usr/bin/env node
// i18n_extract.mjs — scan .vue files for hardcoded Chinese UI strings,
// propose i18n keys, and (optionally) rewrite source + append keys to zh.ts.
//
// This is deliberately conservative: the default mode only writes a PLAN file
// (`scripts/i18n_extract.plan.json`) so you can review what would change. Use
// `--apply` to actually rewrite files.
//
// Patterns we extract (all inside <template>):
//   1. >中文<          → element text node
//   2. placeholder="中文"
//   3. title="中文"
//   4. label="中文"
//   5. description="中文"
//   6. empty-text="中文"
//
// We intentionally SKIP JS strings in <script> blocks here — for ElMessage
// with simple quotes use `pnpm i18n:script-strings` instead.
//
// Key naming: {fileSlug}.{slotType}_{localCounter}
//   e.g. pipelineTaskDetail.text_1, pipelineTaskDetail.placeholder_2
//
// Usage
//   pnpm i18n:extract                              # plan only
//   pnpm i18n:extract -- --apply                   # rewrite files + zh.ts
//   pnpm i18n:extract -- --files src/views/Foo.vue # limit scope
//   pnpm i18n:extract -- --apply --files ...       # targeted apply
//
// After apply: run `pnpm i18n:sync` to fill en/ja/ko.

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const SRC_DIR = path.join(ROOT, 'src')
const ZH_FILE = path.join(ROOT, 'src', 'i18n', 'zh.ts')
const PLAN_FILE = path.join(__dirname, 'i18n_extract.plan.json')

const HAN_RE = /[\u4e00-\u9fff]/

function parseArgs(argv) {
  const args = { apply: false, files: null, max: 0 }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--apply') args.apply = true
    else if (a === '--files' && argv[i + 1]) args.files = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
    else if (a === '--max' && argv[i + 1]) args.max = parseInt(argv[++i], 10) || 0
    else if (a === '--help' || a === '-h') {
      console.log('Usage: node scripts/i18n_extract.mjs [--apply] [--files a.vue,b.vue] [--max N]')
      process.exit(0)
    }
  }
  return args
}

async function walk(dir) {
  const out = []
  async function rec(d) {
    const ents = await fs.readdir(d, { withFileTypes: true })
    for (const ent of ents) {
      const full = path.join(d, ent.name)
      if (ent.isDirectory()) {
        if (ent.name === 'node_modules' || ent.name === 'dist' || ent.name === 'i18n') continue
        await rec(full)
      } else if (ent.isFile() && ent.name.endsWith('.vue')) {
        out.push(full)
      }
    }
  }
  await rec(dir)
  return out
}

function extractTemplate(src) {
  // Naive but reliable: first <template>...</template> block.
  const m = src.match(/<template([^>]*)>([\s\S]*?)<\/template>/)
  if (!m) return null
  return { before: src.slice(0, m.index), attrs: m[1], body: m[2], after: src.slice(m.index + m[0].length) }
}

function fileSlug(filePath) {
  // e.g. src/views/PipelineTaskDetail.vue -> pipelineTaskDetail
  const base = path.basename(filePath, '.vue')
  return base.charAt(0).toLowerCase() + base.slice(1)
}

/**
 * Scan a template body for hardcoded CN strings and return edits to apply.
 * Each edit = { match: original, replacement: new text, cnText: extracted CN, key: dotted key, kind }
 */
function scanTemplate(body, slug) {
  const edits = []
  let counter = { text: 0, placeholder: 0, title: 0, label: 0, description: 0, emptyText: 0 }

  // 1) Element text node: >中文< (between an opening tag `>` and next `<`).
  //    Skip interpolations ({{ ... }}) and skip if there is no CN char.
  //    We conservatively only match when the run is at least 2 chars CN and
  //    doesn't contain `{{`.
  const TEXT_RE = />(\s*[^<>{}\n]*?[\u4e00-\u9fff][^<>{}\n]*?)</g
  let m
  while ((m = TEXT_RE.exec(body)) !== null) {
    const raw = m[1]
    const trimmed = raw.trim()
    if (!trimmed || !HAN_RE.test(trimmed)) continue
    if (trimmed.includes('{{') || trimmed.includes('}}')) continue
    // Skip if already a Vue binding expression (shouldn't happen w/ regex but defensive).
    if (trimmed.startsWith('v-') || trimmed.startsWith(':')) continue
    counter.text += 1
    const key = `${slug}.text_${counter.text}`
    edits.push({ kind: 'text', cnText: trimmed, key, original: `>${raw}<`, replacement: `>{{ t('${key}') }}<` })
  }

  // 2-6) Attributes with CN values. For each we need to switch `foo="x"` to `:foo="t('...')"`.
  const ATTR_KINDS = [
    ['placeholder', 'placeholder'],
    ['title', 'title'],
    ['label', 'label'],
    ['description', 'description'],
    ['empty-text', 'emptyText'],
  ]
  for (const [attr, counterKey] of ATTR_KINDS) {
    const re = new RegExp(`(\\s)${attr}="([^"]*[\\u4e00-\\u9fff][^"]*)"`, 'g')
    while ((m = re.exec(body)) !== null) {
      const prefix = m[1]
      const val = m[2]
      if (!HAN_RE.test(val)) continue
      if (val.includes('{{')) continue
      counter[counterKey] += 1
      const key = `${slug}.${counterKey}_${counter[counterKey]}`
      edits.push({
        kind: counterKey,
        cnText: val,
        key,
        original: `${prefix}${attr}="${val}"`,
        replacement: `${prefix}:${attr}="t('${key}')"`,
      })
    }
  }

  return edits
}

/**
 * Apply a list of edits to a source string. Each edit uses its `original`
 * substring — unique enough in practice because we include surrounding
 * whitespace/brackets. We process by index to avoid overlap.
 */
function applyEdits(src, edits) {
  // Replace in a single pass, matching the first un-replaced occurrence of each original.
  let out = src
  const used = new Set()
  for (const e of edits) {
    const idx = out.indexOf(e.original)
    if (idx < 0) continue
    used.add(e.key)
    out = out.slice(0, idx) + e.replacement + out.slice(idx + e.original.length)
  }
  return { out, applied: Array.from(used) }
}

/**
 * Ensure `t()` is in scope inside the template. Three cases:
 *   1. Existing <script setup lang="ts"> — inject import + const { t } = useI18n()
 *      if not already present.
 *   2. Existing <script setup> (no lang) — same treatment.
 *   3. No <script setup> block at all — add one right before </template>'s
 *      containing trailing content (or at the end of file if nothing else).
 */
function ensureI18nImport(src) {
  const scriptRe = /<script\s+setup(\s+lang="[^"]+")?\s*>([\s\S]*?)<\/script>/
  const m = src.match(scriptRe)

  if (!m) {
    // No script setup block — add a minimal one after </template>.
    const tplEnd = src.indexOf('</template>')
    const insertion = `\n\n<script setup lang="ts">\nimport { useI18n } from 'vue-i18n'\nconst { t } = useI18n()\n</script>\n`
    if (tplEnd < 0) return { src: src + insertion, changed: true }
    const after = src.slice(tplEnd + '</template>'.length)
    return {
      src: src.slice(0, tplEnd + '</template>'.length) + insertion + after,
      changed: true,
    }
  }

  const langAttr = m[1] || ''
  const body = m[2]
  const hasImport = /from\s+['"]vue-i18n['"]/.test(body)
  const hasCall = /useI18n\s*\(/.test(body)
  if (hasImport && hasCall) return { src, changed: false }

  let newBody = body
  if (!hasImport) {
    const importRe = /(^import .+?$)/gm
    let lastIdx = -1
    let mm
    while ((mm = importRe.exec(newBody)) !== null) lastIdx = mm.index + mm[0].length
    const insertion = `\nimport { useI18n } from 'vue-i18n'`
    if (lastIdx > 0) newBody = newBody.slice(0, lastIdx) + insertion + newBody.slice(lastIdx)
    else newBody = insertion + '\n' + newBody
  }
  if (!hasCall) {
    const lines = newBody.split('\n')
    let insertAt = 0
    for (let i = 0; i < lines.length; i++) {
      if (/^import\s/.test(lines[i].trim())) insertAt = i + 1
    }
    lines.splice(insertAt, 0, '', 'const { t } = useI18n()')
    newBody = lines.join('\n')
  }
  const replaced = src.replace(scriptRe, () => `<script setup${langAttr}>${newBody}</script>`)
  return { src: replaced, changed: true }
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

function serializeObj(obj, indent = 0) {
  const pad = '  '.repeat(indent)
  const inner = '  '.repeat(indent + 1)
  const lines = ['{']
  const entries = Object.entries(obj)
  entries.forEach(([k, v], i) => {
    const keyStr = /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k) ? k : JSON.stringify(k)
    let valStr
    if (v && typeof v === 'object' && !Array.isArray(v)) valStr = serializeObj(v, indent + 1)
    else valStr = JSON.stringify(v)
    const comma = i < entries.length - 1 ? ',' : ','
    lines.push(`${inner}${keyStr}: ${valStr}${comma}`)
  })
  lines.push(`${pad}}`)
  return lines.join('\n')
}

async function loadZh() {
  const text = await fs.readFile(ZH_FILE, 'utf8')
  const idx = text.indexOf('export default')
  const header = idx > 0 ? text.slice(0, idx) : ''
  const body = (idx >= 0 ? text.slice(idx) : text).replace(/^export\s+default\s+/, '').trim().replace(/;?\s*$/, '')
  // eslint-disable-next-line no-new-func
  const dict = new Function(`return (${body})`)()
  return { header, dict }
}

async function writeZh(header, dict) {
  const out = `${header}export default ${serializeObj(dict)}\n`
  await fs.writeFile(ZH_FILE, out, 'utf8')
}

async function main() {
  const args = parseArgs(process.argv)
  let files
  if (args.files) {
    files = args.files.map((f) => (path.isAbsolute(f) ? f : path.join(ROOT, f)))
  } else {
    files = await walk(SRC_DIR)
  }

  const plan = []
  for (const file of files) {
    const src = await fs.readFile(file, 'utf8')
    const tpl = extractTemplate(src)
    if (!tpl) continue
    const slug = fileSlug(file)
    const edits = scanTemplate(tpl.body, slug)
    if (!edits.length) continue
    plan.push({ file: path.relative(ROOT, file), slug, count: edits.length, edits })
  }

  const totalEdits = plan.reduce((a, f) => a + f.count, 0)
  const totalFiles = plan.length

  console.log(`[extract] files scanned=${files.length} affected=${totalFiles} edits=${totalEdits}`)
  for (const f of plan) {
    console.log(`  ${f.file.padEnd(60)} ${f.count}`)
  }

  // Always write the plan for human review.
  await fs.writeFile(PLAN_FILE, JSON.stringify(plan, null, 2), 'utf8')
  console.log(`\n[extract] plan written to ${path.relative(ROOT, PLAN_FILE)}`)

  if (!args.apply) {
    console.log(`[extract] dry mode — rerun with --apply to rewrite files and append keys to src/i18n/zh.ts`)
    return
  }

  // APPLY phase.
  const zh = await loadZh()
  let filesChanged = 0
  let keysAdded = 0

  for (const f of plan) {
    if (args.max && keysAdded >= args.max) {
      console.log(`[extract] reached --max=${args.max}, stopping`)
      break
    }
    const abs = path.join(ROOT, f.file)
    let src = await fs.readFile(abs, 'utf8')
    const tpl = extractTemplate(src)
    if (!tpl) continue
    const { out: newBody, applied } = applyEdits(tpl.body, f.edits)
    if (!applied.length) continue

    // Splice new template body back in, then ensure useI18n import in script.
    const newSrc = tpl.before + `<template${tpl.attrs}>` + newBody + `</template>` + tpl.after
    const { src: finalSrc, changed } = ensureI18nImport(newSrc)

    await fs.writeFile(abs, finalSrc, 'utf8')
    filesChanged += 1

    // Append each applied key's original CN to the zh dictionary.
    for (const e of f.edits) {
      if (!applied.includes(e.key)) continue
      setDeep(zh.dict, e.key, e.cnText)
      keysAdded += 1
    }
    console.log(`  patched ${f.file} (+${applied.length} keys${changed ? ', injected useI18n' : ''})`)
  }

  if (keysAdded > 0) {
    await writeZh(zh.header, zh.dict)
    console.log(`\n[extract] ${filesChanged} files rewritten, ${keysAdded} keys appended to src/i18n/zh.ts`)
    console.log(`[extract] next: run \`pnpm i18n:sync\` to fill en/ja/ko for the new keys.`)
  } else {
    console.log(`\n[extract] no edits applied`)
  }
}

main().catch((e) => {
  console.error('[extract] fatal:', e.message)
  process.exit(1)
})
