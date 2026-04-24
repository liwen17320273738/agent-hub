<template>
  <!--
    Left-rail palette of role / stage presets the user can drag onto
    the Vue Flow canvas to add a new stage in one gesture.

    Drag payload protocol (shared with WorkflowBuilder.vue):
      MIME type:  "application/x-agenthub-stage"
      Payload:    JSON.stringify({ role, label, stageId? })

    The drop handler on the canvas reads the payload, projects the
    drop coordinates into Vue Flow space (`useVueFlow().project`),
    and inserts a fresh node at that point with a unique stage_id
    (suffixed if the role/label is already on the canvas).
  -->
  <aside class="stage-palette">
    <div class="palette-header">
      <h3>{{ t('stagePalette.text_1') }}</h3>
      <span class="hint">{{ t('stagePalette.text_2') }}</span>
    </div>
    <ul class="palette-list">
      <li
        v-for="item in items"
        :key="item.role + item.stageId"
        class="palette-item"
        draggable="true"
        @dragstart="(e) => onDragStart(e, item)"
        @dragend="onDragEnd"
      >
        <span class="emoji">{{ roleEmoji(item.role) }}</span>
        <div class="text">
          <div class="label">{{ item.label }}</div>
          <code class="role">{{ roleLabel(item.role) }}</code>
        </div>
      </li>
    </ul>
    <div class="palette-footer">
      <p class="tip">{{ t('stagePalette.text_3') }}<br />{{ t('stagePalette.text_4') }}<br />{{ t('stagePalette.text_5') }}<br />
        · 点节点 = 配置面板
      </p>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { KNOWN_ROLES, roleEmoji, roleLabel } from '@/services/workflowBuilder'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface PaletteItem {
  role: string
  /** Default human label that lands in the new node. */
  label: string
  /** Default stage_id seed; the canvas appends a suffix if it collides. */
  stageId: string
}

// One palette item per known role. Defaults pick the most natural
// stage_id we'd see in the existing PIPELINE_TEMPLATES so a quick
// drag-out matches "what the templates look like" without surprises.
const STAGE_DEFAULTS: Record<string, { stageId: string; label: string }> = {
  'product-manager': { stageId: 'planning',     label: '需求规划' },
  designer:          { stageId: 'design',       label: 'UI/UX 设计' },
  architect:         { stageId: 'architecture', label: '架构设计' },
  developer:         { stageId: 'development',  label: '开发实现' },
  'qa-lead':         { stageId: 'testing',      label: '测试验证' },
  security:          { stageId: 'security',     label: '安全审计' },
  legal:             { stageId: 'legal',        label: '法务合规' },
  finance:           { stageId: 'finance',      label: '财务评估' },
  data:              { stageId: 'data',         label: '数据建模' },
  marketing:         { stageId: 'marketing',    label: '增长营销' },
  acceptance:        { stageId: 'reviewing',    label: '审查验收' },
  devops:            { stageId: 'deployment',   label: '部署上线' },
}

const items: PaletteItem[] = KNOWN_ROLES.map((r) => {
  const d = STAGE_DEFAULTS[r.value] || { stageId: r.value, label: r.label }
  return { role: r.value, label: d.label, stageId: d.stageId }
})

const MIME = 'application/x-agenthub-stage'

function onDragStart(e: DragEvent, item: PaletteItem) {
  if (!e.dataTransfer) return
  e.dataTransfer.effectAllowed = 'move'
  // Some browsers ignore custom MIME — set both. The canvas reads MIME
  // first (faster + uncontaminated by other dragged text) and falls
  // back to text/plain.
  e.dataTransfer.setData(MIME, JSON.stringify(item))
  e.dataTransfer.setData('text/plain', JSON.stringify(item))
}

function onDragEnd(_e: DragEvent) {
  // Hook for visuals if we ever need to fade the source — keep as a
  // no-op for now so the API stays stable.
}
</script>

<style scoped>
.stage-palette {
  width: 220px;
  flex-shrink: 0;
  background: #0f172a;
  border-right: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.palette-header {
  padding: 14px 16px 8px;
  border-bottom: 1px solid #1e293b;
}
.palette-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.palette-header .hint {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #64748b;
}

.palette-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  margin: 4px 0;
  background: #1f2937;
  border: 1px solid #1e293b;
  border-radius: 8px;
  cursor: grab;
  user-select: none;
  transition: border-color 0.12s, transform 0.08s;
}
.palette-item:hover {
  border-color: #38bdf8;
}
.palette-item:active {
  cursor: grabbing;
  transform: scale(0.98);
}
.palette-item .emoji {
  font-size: 18px;
  line-height: 1;
}
.palette-item .text {
  flex: 1;
  min-width: 0;
}
.palette-item .label {
  font-size: 12px;
  font-weight: 500;
  color: #f1f5f9;
}
.palette-item .role {
  display: block;
  margin-top: 2px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  color: #94a3b8;
  background: transparent;
  padding: 0;
}

.palette-footer {
  border-top: 1px solid #1e293b;
  padding: 10px 14px;
  background: #0b1120;
}
.palette-footer .tip {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: #94a3b8;
}
</style>
