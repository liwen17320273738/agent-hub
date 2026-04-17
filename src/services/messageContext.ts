import type { ChatMessage, PipelineTask } from '@/agents/types'
import type { LLMMessage } from './llm'

/** 控制成本与上下文上限：条数 + 字符预算（中文约 2–3 字/token，留余量） */
const DEFAULT_MAX_MESSAGES = 32
const DEFAULT_MAX_CONTEXT_CHARS = 48000

export function buildPipelineContext(task: PipelineTask): string {
  const parts: string[] = []
  parts.push(`\n\n【当前流水线任务上下文】`)
  parts.push(`- 任务ID: ${task.id}`)
  parts.push(`- 标题: ${task.title}`)
  parts.push(`- 当前阶段: ${task.currentStageId}`)
  parts.push(`- 状态: ${task.status}`)
  if (task.description) {
    parts.push(`- 需求描述: ${task.description}`)
  }

  const completedStages = task.stages.filter((s) => s.status === 'done' && s.output)
  for (const stage of completedStages) {
    parts.push(`\n【${stage.label} 产出】\n${stage.output}`)
  }

  if (task.artifacts?.length) {
    parts.push(`\n【交付产物】`)
    for (const artifact of task.artifacts.slice(-3)) {
      const preview =
        artifact.type === 'upload_image' || artifact.type === 'upload_file'
          ? `(文件附件，mime=${artifact.metadata?.mime ?? 'unknown'})`
          : (artifact.content || '').slice(0, 500)
      parts.push(`- [${artifact.type}] ${artifact.name}: ${preview}`)
    }
  }

  parts.push(`\n请基于以上流水线上下文继续工作。你当前负责的阶段是: ${task.currentStageId}。`)
  return parts.join('\n')
}

/**
 * 从完整对话历史构造发给模型的 messages：保留末尾若干轮，避免超长与费用失控。
 */
export function buildLLMMessages(
  systemPrompt: string,
  history: ChatMessage[],
  options?: {
    maxMessages?: number
    maxContextChars?: number
    /** 会话级摘要，补充被滑动窗口裁掉的早前信息 */
    memorySummary?: string
    /** 流水线任务上下文 */
    pipelineTask?: PipelineTask
  },
): LLMMessage[] {
  const maxMessages = options?.maxMessages ?? DEFAULT_MAX_MESSAGES
  const maxChars = options?.maxContextChars ?? DEFAULT_MAX_CONTEXT_CHARS

  const relevant = history.filter((m) => m.role === 'user' || m.role === 'assistant')
  let slice = relevant
  let dropped = false

  if (slice.length > maxMessages) {
    slice = slice.slice(-maxMessages)
    dropped = true
  }

  let total = slice.reduce((s, m) => s + m.content.length, 0)
  while (slice.length > 1 && total > maxChars) {
    slice = slice.slice(1)
    dropped = true
    total = slice.reduce((s, m) => s + m.content.length, 0)
  }

  while (slice.length > 0 && slice[0].role === 'assistant') {
    slice = slice.slice(1)
    dropped = true
  }

  let systemContent = systemPrompt
  if (options?.pipelineTask) {
    systemContent += buildPipelineContext(options.pipelineTask)
  }
  const sum = options?.memorySummary?.trim()
  if (sum) {
    systemContent += `\n\n【早前对话摘要（仅供参考，勿编造细节）】\n${sum}`
  }
  if (dropped) {
    systemContent +=
      '\n\n（内部说明：因长度限制，更早的多轮对话未包含在本次请求中。请勿编造未出现的用户原话；若需历史细节请让用户补充。）'
  }

  return [
    { role: 'system', content: systemContent },
    ...slice.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    })),
  ]
}
