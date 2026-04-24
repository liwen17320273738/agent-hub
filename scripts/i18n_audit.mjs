#!/usr/bin/env node
// List i18n keys used in src/ (static $t('...') / t('...')) missing from zh.ts flat map.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const ZH = path.join(ROOT, 'src', 'i18n', 'zh.ts')

async function loadZh() {
  const text = await fs.readFile(ZH, 'utf8')
  const idx = text.indexOf('export default')
  const body = (idx >= 0 ? text.slice(idx) : text).replace(/^export\s+default\s+/, '').trim().replace(/;?\s*$/, '')
  return new Function(`return (${body})`)()
}

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out)
    else out[key] = v
  }
  return out
}

async function walk(dir) {
  const out = []
  const ents = await fs.readdir(dir, { withFileTypes: true })
  for (const e of ents) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'i18n' || e.name === 'node_modules') continue
      out.push(...(await walk(full)))
    } else if (e.name.endsWith('.vue') || e.name.endsWith('.ts')) {
      out.push(full)
    }
  }
  return out
}

/** Static keys from $t('a.b') t("a.b") — skip template literals and concatenation */
function extractKeys(src) {
  const keys = new Set()
  const re = /(?:\$t|\bt)\(\s*['"]([a-zA-Z0-9_.-]+)['"]/g
  let m
  while ((m = re.exec(src)) !== null) {
    keys.add(m[1])
  }
  return keys
}

async function main() {
  const zh = await loadZh()
  const flat = flatten(zh)
  const have = new Set(Object.keys(flat))
  const files = await walk(SRC)
  const used = new Set()
  for (const f of files) {
    const text = await fs.readFile(f, 'utf8')
    for (const k of extractKeys(text)) used.add(k)
  }
  const missing = [...used].filter((k) => !have.has(k)).sort()
  console.log(`[i18n-audit] zh keys=${have.size} static refs=${used.size} missing=${missing.length}`)
  if (missing.length) {
    console.log(missing.join('\n'))
    process.exitCode = 1
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
