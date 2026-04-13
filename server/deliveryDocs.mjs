import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export const DELIVERY_DIR = join(__dirname, '..', 'docs', 'delivery')

export const DELIVERY_DOCS = [
  {
    name: '01-prd.md',
    title: 'PRD',
    description: '背景、目标、范围、非目标、用户故事、验收标准、开放问题。',
    template: `# PRD：<标题>

- 版本 / 日期：

## 背景与目标

## 用户与场景

## 范围与非目标

## 用户故事与验收标准

## 里程碑

## 开放问题

## 与规则基线的注意点
`,
  },
  {
    name: '02-ui-spec.md',
    title: 'UI Spec',
    description: '页面、组件、状态、关键交互与异常流说明。',
    template: `# UI Spec：<标题>

## 页面清单

## 关键流程

## 组件与布局

## 状态设计

## 异常态 / 空态 / 加载态

## 可访问性与还原注意点
`,
  },
  {
    name: '03-architecture.md',
    title: 'Architecture',
    description: '边界、契约、数据流、风险、失败路径与 ADR。',
    template: `# Architecture：<标题>

## 上下文与边界

## 模块划分

## API / 契约

## 数据与状态

## 失败路径与观测

## ADR
`,
  },
  {
    name: '04-implementation-notes.md',
    title: 'Implementation Notes',
    description: '实现顺序、入口路径、配置、验证方式、偏差与回滚注意。',
    template: `# Implementation Notes：<标题>

## 实现范围

## 修改点

## 入口路径 / 环境变量 / 开关

## 验证方式

## 已知偏差

## 回滚注意
`,
  },
  {
    name: '05-test-report.md',
    title: 'Test Report',
    description: '测试范围、已执行项、未执行项、风险与结论。',
    template: `# Test Report：<标题>

## 测试范围

## 已执行

## 未执行 / 阻塞项

## 发现的问题

## 风险评估

## 结论
`,
  },
  {
    name: '06-acceptance.md',
    title: 'Acceptance',
    description: '验收结论、发布建议、回滚和监控检查项。',
    template: `# Acceptance：<标题>

## 验收结论

## 发布说明

## 回滚方案

## 监控检查项

## 已知问题
`,
  },
]

export async function ensureDeliveryDir() {
  await mkdir(DELIVERY_DIR, { recursive: true })
}

export async function ensureDeliveryTemplates() {
  await ensureDeliveryDir()
  for (const doc of DELIVERY_DOCS) {
    const filePath = join(DELIVERY_DIR, doc.name)
    if (!existsSync(filePath)) {
      await writeFile(filePath, doc.template, 'utf8')
    }
  }
}

export async function listDeliveryDocs() {
  await ensureDeliveryTemplates()
  const files = new Set(await readdir(DELIVERY_DIR).catch(() => []))
  const result = []
  for (const doc of DELIVERY_DOCS) {
    const filePath = join(DELIVERY_DIR, doc.name)
    if (files.has(doc.name)) {
      const info = await stat(filePath)
      result.push({
        ...doc,
        exists: true,
        updatedAt: info.mtimeMs,
      })
    } else {
      result.push({
        ...doc,
        exists: false,
        updatedAt: null,
      })
    }
  }
  return result
}

export async function readDeliveryDoc(name) {
  await ensureDeliveryTemplates()
  const filePath = join(DELIVERY_DIR, name)
  const content = await readFile(filePath, 'utf8')
  const info = await stat(filePath)
  const meta = DELIVERY_DOCS.find((doc) => doc.name === name)
  return {
    name,
    title: meta?.title ?? name,
    description: meta?.description ?? '',
    content,
    updatedAt: info.mtimeMs,
  }
}

export async function writeDeliveryDoc(name, content) {
  await ensureDeliveryDir()
  const filePath = join(DELIVERY_DIR, name)
  await writeFile(filePath, content, 'utf8')
  const info = await stat(filePath)
  const meta = DELIVERY_DOCS.find((doc) => doc.name === name)
  return {
    name,
    title: meta?.title ?? name,
    description: meta?.description ?? '',
    content,
    updatedAt: info.mtimeMs,
  }
}
