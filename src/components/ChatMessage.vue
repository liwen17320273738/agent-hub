<template>
  <div class="message-row" :class="[message.role, { streaming }]">
    <div class="message-container">
      <div class="avatar" v-if="message.role === 'assistant'">
        <el-icon :size="18" :style="{ color: agent?.color }">
          <component :is="resolveAgentIcon(agent?.icon || 'ChatDotRound')" />
        </el-icon>
      </div>
      <div class="avatar user-avatar" v-else>
        <el-icon :size="18"><User /></el-icon>
      </div>

      <div class="message-content">
        <div class="message-meta">
          <span class="sender">{{ message.role === 'user' ? '你' : agent?.name }}</span>
          <span class="time" v-if="!streaming">{{ formatTime(message.timestamp) }}</span>
          <div class="message-actions" v-if="!streaming">
            <el-button text type="primary" size="small" @click.stop="copyContent">{{ t('chatMessage.text_1') }}</el-button>
            <el-button
              v-if="showRegenerate"
              text
              type="primary"
              size="small"
              @click.stop="$emit('regenerate')"
            >
              重新生成
            </el-button>
            <el-button
              v-if="message.role === 'user' && showEditUser"
              text
              type="primary"
              size="small"
              @click.stop="$emit('editUser', message)"
            >
              编辑
            </el-button>
          </div>
        </div>
        <div class="message-body" v-html="renderedContent" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { ChatMessage } from '@/agents/types'
import type { AgentConfig } from '@/agents/types'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineEmits<{
  regenerate: []
  editUser: [m: ChatMessage]
}>()

const props = defineProps<{
  message: ChatMessage
  agent?: AgentConfig
  streaming?: boolean
  /** 最后一条助手消息时可重新请求模型 */
  showRegenerate?: boolean
  /** 用户消息可编辑并重发（删除该条之后的历史） */
  showEditUser?: boolean
}>()

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    ElMessage.success(t('chatMessage.elMessage_1'))
  } catch {
    ElMessage.error(t('chatMessage.elMessage_2'))
  }
}

function formatTime(ts: number) {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const renderedContent = computed(() => {
  let text = props.message.content
  text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  // Code blocks
  text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre class="code-block"><code class="language-${lang}">${code.trim()}</code></pre>`
  })

  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // Italic
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Lists
  text = text.replace(/^(\d+)\. (.+)$/gm, '<li class="ol-item">$2</li>')
  text = text.replace(/^[-*] (.+)$/gm, '<li class="ul-item">$1</li>')

  // Headers
  text = text.replace(/^### (.+)$/gm, '<h4>$1</h4>')
  text = text.replace(/^## (.+)$/gm, '<h3>$1</h3>')
  text = text.replace(/^# (.+)$/gm, '<h2>$1</h2>')

  // Line breaks
  text = text.replace(/\n/g, '<br>')

  return text
})
</script>

<style scoped>
.message-row {
  padding: 4px 24px;
}

.message-row.user {
  background: transparent;
}

.message-row.assistant {
  background: var(--bg-secondary);
}

.message-container {
  display: flex;
  gap: 14px;
  max-width: 800px;
  margin: 0 auto;
  padding: 16px 0;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.user-avatar {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}

.sender {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.time {
  font-size: 11px;
  color: var(--text-muted);
}

.message-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.message-row:hover .message-actions {
  opacity: 1;
}

@media (hover: none) {
  .message-actions {
    opacity: 1;
  }
}

.message-body {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-primary);
  word-break: break-word;
}

.message-body :deep(h2),
.message-body :deep(h3),
.message-body :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
}

.message-body :deep(h2) { font-size: 18px; }
.message-body :deep(h3) { font-size: 16px; }
.message-body :deep(h4) { font-size: 15px; }

.message-body :deep(strong) {
  font-weight: 600;
  color: var(--text-primary);
}

.message-body :deep(.inline-code) {
  background: var(--bg-tertiary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  color: #e06c75;
}

.message-body :deep(.code-block) {
  background: #1a1a2e;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  margin: 12px 0;
  overflow-x: auto;
}

.message-body :deep(.code-block code) {
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #abb2bf;
}

.message-body :deep(li) {
  margin-left: 20px;
  margin-bottom: 4px;
}

.message-body :deep(.ol-item) {
  list-style: decimal;
}

.message-body :deep(.ul-item) {
  list-style: disc;
}

.streaming .message-body::after {
  content: '▊';
  animation: blink 0.8s infinite;
  color: var(--accent);
}

@keyframes blink {
  50% { opacity: 0; }
}
</style>
