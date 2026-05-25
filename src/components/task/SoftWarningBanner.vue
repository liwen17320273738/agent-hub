<template>
  <section v-if="softWarnings.length" class="soft-warning-banner">
    <div class="sw-icon">⚠️</div>
    <div class="sw-body">
      <div class="sw-title">{{ t('softWarning.title') }}</div>
      <ul class="sw-list">
        <li v-for="(w, i) in softWarnings" :key="i">
          <span class="sw-stage">{{ w.stageLabel }}</span>
          <span class="sw-text">{{ w.message }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface StageLike {
  id: string
  label?: string
  status?: string
  gate_status?: string
  gateStatus?: string
  gate_details?: { suggestions?: string[] } | null
  gateDetails?: { suggestions?: string[] } | null
}

const props = defineProps<{
  stages: StageLike[]
}>()

const { t } = useI18n()

interface SoftWarningItem {
  stageLabel: string
  message: string
}

const softWarnings = computed<SoftWarningItem[]>(() => {
  const out: SoftWarningItem[] = []
  for (const s of props.stages || []) {
    if (s.status === 'failed' || s.status === 'error' || s.status === 'blocked') continue
    const gs = s.gate_status || s.gateStatus
    if (gs !== 'warning') continue
    const details = s.gate_details || s.gateDetails
    const sugg = details?.suggestions || []
    for (const msg of sugg) {
      if (!msg) continue
      out.push({ stageLabel: s.label || s.id, message: msg })
    }
  }
  return out
})
</script>

<style scoped>
.soft-warning-banner {
  margin: 16px 0;
  padding: 14px 18px;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.sw-icon {
  font-size: 22px;
  line-height: 1;
}
.sw-title {
  font-weight: 600;
  color: #92400e;
  margin-bottom: 6px;
  font-size: 14px;
}
.sw-list {
  margin: 0;
  padding-left: 18px;
  color: #78350f;
  font-size: 13px;
}
.sw-list li { margin-bottom: 4px; }
.sw-stage {
  display: inline-block;
  min-width: 80px;
  font-weight: 600;
  color: #b45309;
  margin-right: 8px;
}
</style>
