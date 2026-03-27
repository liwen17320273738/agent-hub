/** 将数据库行转为 API 对话对象（snake_case → camelCase） */
export function rowToConversation(row) {
  let messages = []
  try {
    messages = JSON.parse(row.messages_json || '[]')
  } catch {
    messages = []
  }
  const rev = row.revision != null ? Number(row.revision) : 0
  return {
    id: row.id,
    agentId: row.agent_id,
    title: row.title,
    messages,
    summary: row.summary || undefined,
    createdAt: Number(row.created_at),
    updatedAt: Number(row.updated_at),
    revision: Number.isFinite(rev) ? rev : 0,
  }
}
