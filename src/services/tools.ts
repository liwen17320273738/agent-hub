export type ToolCall = {
  id: string
  type: 'function'
  function: { name: string; arguments: string }
}

/** OpenAI Chat Completions 兼容的 tools 定义 */
export const TOOL_DEFINITIONS = [
  {
    type: 'function' as const,
    function: {
      name: 'get_current_datetime',
      description: '返回当前日期与时间（用户浏览器本地时区）。用于回答「现在几点」「今天星期几」等。',
      parameters: {
        type: 'object',
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'text_word_count',
      description: '统计文本字符数与大致字数（含中文），用于长度预估、是否超限等。',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: '要统计的完整文本' },
        },
        required: ['text'],
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'random_integer',
      description: '在闭区间 [min, max] 内生成均匀随机整数，用于抽签、骰子、抽样等。',
      parameters: {
        type: 'object',
        properties: {
          min: { type: 'integer', description: '下限（含）' },
          max: { type: 'integer', description: '上限（含）' },
        },
        required: ['min', 'max'],
      },
    },
  },
]

function safeJsonParse(s: string): Record<string, unknown> {
  try {
    const v = JSON.parse(s || '{}')
    return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

export function executeTool(name: string, argsJson: string): string {
  const args = safeJsonParse(argsJson)
  try {
    switch (name) {
      case 'get_current_datetime': {
        return new Date().toLocaleString('zh-CN', {
          weekday: 'long',
          year: 'numeric',
          month: 'long',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      }
      case 'text_word_count': {
        const text = String(args.text ?? '')
        const chars = text.length
        const cjk = (text.match(/[\u4e00-\u9fff]/g) ?? []).length
        const nonSpace = text.replace(/\s/g, '').length
        return JSON.stringify(
          { 字符数: chars, 去除空白后长度: nonSpace, 汉字约数: cjk },
          null,
          0,
        )
      }
      case 'random_integer': {
        let min = Number(args.min)
        let max = Number(args.max)
        if (!Number.isFinite(min) || !Number.isFinite(max))
          return JSON.stringify({ error: 'min/max 须为有效数字' })
        min = Math.ceil(min)
        max = Math.floor(max)
        if (min > max) [min, max] = [max, min]
        if (max - min > 1_000_000) return JSON.stringify({ error: '区间过大' })
        const n = Math.floor(Math.random() * (max - min + 1)) + min
        return JSON.stringify({ value: n, min, max })
      }
      default:
        return JSON.stringify({ error: `未知工具: ${name}` })
    }
  } catch (e) {
    return JSON.stringify({ error: e instanceof Error ? e.message : String(e) })
  }
}
