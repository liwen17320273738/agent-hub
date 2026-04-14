/**
 * Skills System — deer-flow 风格的技能加载系统
 *
 * Skills 是以 SKILL.md 定义的知识包，含 YAML frontmatter + Markdown 正文。
 * 启用后会注入到 Lead Agent / Subagent 的 system prompt 中，
 * 赋予 Agent 特定领域的专业能力。
 *
 * 目录结构:
 *   skills/
 *     public/        — 内置技能
 *     custom/        — 用户自定义技能
 */

import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { existsSync } from 'node:fs'

const SKILLS_ROOT = resolve(process.cwd(), 'skills')
const CONFIG_FILE = resolve(process.cwd(), 'skills/config.json')

let _skillsCache = null
let _cacheTime = 0
const CACHE_TTL = 30_000

export async function loadSkills(forceReload = false) {
  if (!forceReload && _skillsCache && Date.now() - _cacheTime < CACHE_TTL) {
    return _skillsCache
  }

  const config = await loadSkillConfig()
  const skills = []

  for (const category of ['public', 'custom']) {
    const dir = join(SKILLS_ROOT, category)
    if (!existsSync(dir)) continue

    let entries
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch {
      continue
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const skillFile = join(dir, entry.name, 'SKILL.md')
      if (!existsSync(skillFile)) continue

      try {
        const raw = await readFile(skillFile, 'utf-8')
        const parsed = parseSkillMd(raw)
        const skillName = parsed.frontmatter.name || entry.name
        const enabled = config.enabled?.[skillName] ?? parsed.frontmatter.enabled ?? true

        skills.push({
          name: skillName,
          description: parsed.frontmatter.description || '',
          category,
          enabled,
          license: parsed.frontmatter.license || '',
          content: parsed.content,
          path: skillFile,
        })
      } catch {
        // skip invalid skill files
      }
    }
  }

  _skillsCache = skills
  _cacheTime = Date.now()
  return skills
}

export async function getEnabledSkillsPrompt() {
  const skills = await loadSkills()
  const enabled = skills.filter(s => s.enabled)
  if (!enabled.length) return ''

  return '\n\n<enabled_skills>\n' +
    enabled.map(s => `## Skill: ${s.name}\n${s.content}`).join('\n\n') +
    '\n</enabled_skills>'
}

export async function toggleSkill(skillName, enabled) {
  const config = await loadSkillConfig()
  if (!config.enabled) config.enabled = {}
  config.enabled[skillName] = enabled
  await saveSkillConfig(config)
  _skillsCache = null
  return { ok: true, skillName, enabled }
}

export async function listSkills() {
  return loadSkills(true)
}

function parseSkillMd(raw) {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return { frontmatter: {}, content: raw }

  const yamlStr = match[1]
  const content = match[2].trim()

  const frontmatter = {}
  for (const line of yamlStr.split('\n')) {
    const colonIdx = line.indexOf(':')
    if (colonIdx === -1) continue
    const key = line.slice(0, colonIdx).trim()
    let value = line.slice(colonIdx + 1).trim()
    if (value === 'true') value = true
    else if (value === 'false') value = false
    frontmatter[key] = value
  }

  return { frontmatter, content }
}

async function loadSkillConfig() {
  try {
    const raw = await readFile(CONFIG_FILE, 'utf-8')
    return JSON.parse(raw)
  } catch {
    return { enabled: {} }
  }
}

async function saveSkillConfig(config) {
  await mkdir(SKILLS_ROOT, { recursive: true })
  await writeFile(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf-8')
}

export async function ensureSkillsDirs() {
  await mkdir(join(SKILLS_ROOT, 'public'), { recursive: true })
  await mkdir(join(SKILLS_ROOT, 'custom'), { recursive: true })
}
