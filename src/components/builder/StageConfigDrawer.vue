<template>
  <!--
    Right-side drawer that edits a single BuilderNode's `data`.

    Uses ``v-model`` two-way binding on each Element Plus control so
    parent state (Vue Flow's nodes array) updates in real time. The
    parent is responsible for re-running topology validation after
    every change — the drawer doesn't know about the rest of the graph.

    Why no save button? The builder is "live" — every keystroke
    persists to localStorage via the parent's debounced watcher. A
    "Save" button would imply revertable drafts, which we don't
    have yet. If we add undo/redo, we'll add a button then.
  -->
  <el-drawer
    v-model="visibleProxy"
    :title="`配置阶段 · ${data?.label || data?.stageId || ''}`"
    direction="rtl"
    size="380px"
    :destroy-on-close="false"
    :before-close="handleClose"
  >
    <div v-if="data" class="cfg-form">
      <el-form label-position="top" size="default">
        <el-form-item label="阶段 ID（stage_id）">
          <el-input
            v-model="data.stageId"
            placeholder="development"
            clearable
            @input="onStageIdInput"
          >
            <template #append>
              <el-tooltip content="后端使用的稳定标识；建议小写英文，含字母数字和短横线">
                <el-icon><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
          </el-input>
          <div v-if="stageIdError" class="hint hint-error">{{ stageIdError }}</div>
          <div v-else class="hint">仅小写字母 / 数字 / 短横线，会成为 PipelineStage 的主键</div>
        </el-form-item>

        <el-form-item label="显示名称">
          <el-input v-model="data.label" placeholder="开发实现" clearable />
        </el-form-item>

        <el-form-item label="Agent 角色">
          <el-select v-model="data.role" placeholder="选择角色" style="width: 100%">
            <el-option
              v-for="r in KNOWN_ROLES"
              :key="r.value"
              :label="`${r.emoji}  ${r.label}（${r.value}）`"
              :value="r.value"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">高级</el-divider>

        <el-form-item label="模型覆盖（可选）">
          <el-input
            v-model="modelInput"
            placeholder="留空 = 走 LLM router 默认"
            clearable
            @blur="commitModel"
            @keyup.enter="commitModel"
          />
          <div class="hint">填了就锁定；常用：claude-sonnet-4、gpt-4o、deepseek-chat</div>
        </el-form-item>

        <el-form-item label="质量阈值">
          <el-slider
            :model-value="(data.qualityGateMin ?? 0) * 100"
            :min="0"
            :max="100"
            :step="5"
            :format-tooltip="(v: number) => v === 0 ? '关闭' : `${v}%`"
            @input="(v: number) => (data.qualityGateMin = v === 0 ? undefined : v / 100)"
          />
          <div class="hint">
            self-verify 评分低于阈值时自动 reject + self-heal；0 = 关闭
          </div>
        </el-form-item>

        <el-form-item label="Reject 时执行">
          <el-radio-group v-model="rejectActionProxy" size="small">
            <el-radio-button value="self-heal">自动改 prompt</el-radio-button>
            <el-radio-button value="escalate">升级人工</el-radio-button>
            <el-radio-button value="manual">仅记录</el-radio-button>
          </el-radio-group>
          <div class="hint">
            <strong>self-heal</strong>: AI 自动读取 reject 反馈再跑一次（推荐）<br />
            <strong>escalate</strong>: 直接打 IM + 加 Jira/GitHub label<br />
            <strong>manual</strong>: 等人按"重试"
          </div>
        </el-form-item>

        <el-form-item label="失败策略">
          <el-radio-group v-model="onFailureProxy" size="small">
            <el-radio-button value="halt">中止</el-radio-button>
            <el-radio-button value="rollback">回滚</el-radio-button>
            <el-radio-button value="skip">跳过</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="data.humanGate">
            该阶段需要人工审批后才能继续
          </el-checkbox>
        </el-form-item>
      </el-form>

      <el-divider content-position="left">依赖关系</el-divider>
      <div class="deps-block">
        <div v-if="dependsOn.length === 0" class="hint">
          无（这是入口阶段）。在画布上从其他节点拖一条线到此节点的左侧把手即可。
        </div>
        <div v-else class="dep-list">
          <el-tag
            v-for="d in dependsOn"
            :key="d"
            type="info"
            effect="dark"
            size="default"
          >
            {{ d }}
          </el-tag>
        </div>
      </div>

      <div class="footer-actions">
        <el-button type="danger" plain size="small" @click="emit('delete', nodeId)">
          <el-icon><Delete /></el-icon>
          删除此阶段
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete, InfoFilled } from '@element-plus/icons-vue'
import { KNOWN_ROLES } from '@/services/workflowBuilder'
import type { BuilderNode } from '@/services/workflowBuilder'

const props = defineProps<{
  visible: boolean
  nodeId: string | null
  data: BuilderNode['data'] | null
  /** Stage ids upstream of this node, derived in the parent. */
  dependsOn: string[]
  /** Other nodes' stage ids — for dup detection. */
  otherStageIds: string[]
}>()

const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'delete', id: string): void
}>()

const visibleProxy = computed({
  get: () => props.visible,
  set: (v) => emit('update:visible', v),
})

// Local model field — committed on blur to avoid re-rendering the
// canvas on every keystroke. Empty string ⇒ unset (back to router).
const modelInput = ref('')
watch(
  () => props.data?.model,
  (v) => {
    modelInput.value = v || ''
  },
  { immediate: true },
)
function commitModel() {
  if (!props.data) return
  props.data.model = modelInput.value.trim() || null
}

const rejectActionProxy = computed({
  get: () => props.data?.rejectAction || 'self-heal',
  set: (v) => {
    if (props.data) props.data.rejectAction = v as 'self-heal' | 'escalate' | 'manual'
  },
})

const onFailureProxy = computed({
  get: () => props.data?.onFailure || 'halt',
  set: (v) => {
    if (props.data) props.data.onFailure = v as 'halt' | 'rollback' | 'skip'
  },
})

// Stage-id validation: lowercase / digits / dashes only, and must
// not collide with a sibling's stage id. We surface the message
// inline; the parent decides whether to refuse the save based on
// `builderToStages` returning duplicate-stage-id.
const STAGE_ID_RE = /^[a-z][a-z0-9-]{0,40}$/
const stageIdError = computed(() => {
  const id = props.data?.stageId || ''
  if (!id) return '不能为空'
  if (!STAGE_ID_RE.test(id)) return '仅小写字母 / 数字 / 短横线，首字符必须为字母'
  if (props.otherStageIds.includes(id)) return `已存在同名阶段：${id}`
  return ''
})

function onStageIdInput(v: string) {
  if (props.data) props.data.stageId = v.toLowerCase().replace(/\s+/g, '-')
}

function handleClose(done: () => void) {
  // We don't actually block close even when stageIdError is set —
  // the parent's "Run" / "Export" guards will still refuse to ship
  // a broken graph. Easier UX: let people close, fix later.
  done()
}
</script>

<style scoped>
.cfg-form {
  padding: 4px 6px 80px 6px;
}
.hint {
  margin-top: 4px;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.4;
}
.hint-error {
  color: #ef4444;
  font-weight: 500;
}
.deps-block {
  margin-top: 4px;
}
.dep-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.footer-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}
</style>
