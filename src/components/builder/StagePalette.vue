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
        {{ $t('stagePalette.clickNode') }}
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
  'product-manager': { stageId: 'planning',     label: t('stagePalette.productManager') },
  designer:          { stageId: 'design',       label: t('stagePalette.designer') },
  architect:         { stageId: 'architecture', label: t('stagePalette.architect') },
  developer:         { stageId: 'development',  label: t('stagePalette.developer') },
  'qa-lead':         { stageId: 'testing',      label: t('stagePalette.qaLead') },
  security:          { stageId: 'security',     label: t('stagePalette.security') },
  legal:             { stageId: 'legal',        label: t('stagePalette.legal') },
  finance:           { stageId: 'finance',      label: t('stagePalette.finance') },
  data:              { stageId: 'data',         label: t('stagePalette.data') },
  marketing:         { stageId: 'marketing',    label: t('stagePalette.marketing') },
  acceptance:        { stageId: 'reviewing',    label: t('stagePalette.acceptance') },
  devops:            { stageId: 'deployment',   label: t('stagePalette.devops') },
}

const items: PaletteItem[] = KNOWN_ROLES.map((r) => {
  const d = STAGE_DEFAULTS[r.value] || { stageId: r.value, label: r.label }
  return { role: r.value, label: t(`stages.${d.stageId}`), stageId: d.stageId }
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
  font-size: 12px;
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
  font-size: 12px;
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
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
}
</style>
