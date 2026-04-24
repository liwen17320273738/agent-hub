<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SkillsPanel from '@/components/SkillsPanel.vue'

const { t } = useI18n()
</script>

<template>
  <div class="skills-view">
    <SkillsPanel>
      <template #page-title>{{ t('skills.title') }}</template>
      <template #page-subtitle>{{ t('skills.pageSubtitle') }}</template>
    </SkillsPanel>
  </div>
</template>

<style scoped>
.skills-view {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 28px 48px;
}
</style>
