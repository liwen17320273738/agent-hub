<script setup lang="ts">
import SkillsPanel from '@/components/SkillsPanel.vue'
</script>

<template>
  <div class="skills-view">
    <div class="page-header">
      <h1>技能中心</h1>
      <p class="page-subtitle">
        管理 Lead Agent 和子 Agent 的技能扩展。每个技能以 SKILL.md 定义，启用后会注入到 Agent 的系统提示词中。
      </p>
    </div>
    <SkillsPanel />
  </div>
</template>

<style scoped>
.skills-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px;
}
.page-header h1 {
  margin: 0;
  font-size: 24px;
}
.page-subtitle {
  color: var(--text-secondary, #606266);
  font-size: 14px;
  margin-top: 8px;
}
</style>
