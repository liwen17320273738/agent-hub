<script setup lang="ts">
/**
 * SkillsPanel — deer-flow 风格的技能管理面板
 * 展示所有已加载的技能，支持启用/禁用
 */
import { ref, onMounted } from 'vue'
import { fetchSkills, toggleSkill, type Skill } from '@/services/pipelineApi'

const skills = ref<Skill[]>([])
const loading = ref(false)
const expandedSkill = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    skills.value = await fetchSkills()
  } catch {
    skills.value = []
  } finally {
    loading.value = false
  }
}

async function handleToggle(skill: Skill) {
  try {
    await toggleSkill(skill.name, !skill.enabled)
    skill.enabled = !skill.enabled
  } catch (e: unknown) {
    console.error('Toggle skill failed:', e)
  }
}

function toggleExpand(name: string) {
  expandedSkill.value = expandedSkill.value === name ? null : name
}

onMounted(load)
</script>

<template>
  <div class="skills-panel">
    <div class="panel-header">
      <h3>
        <span class="icon">🧩</span>
        技能中心
      </h3>
      <button class="refresh-btn" @click="load" :disabled="loading">
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <div v-if="!skills.length && !loading" class="empty-state">
      暂无可用技能。将 SKILL.md 放入 skills/public 或 skills/custom 目录。
    </div>

    <div v-for="skill in skills" :key="skill.name" class="skill-card" :class="{ disabled: !skill.enabled }">
      <div class="skill-header" @click="toggleExpand(skill.name)">
        <div class="skill-info">
          <span class="skill-name">{{ skill.name }}</span>
          <span class="skill-category" :class="skill.category">{{ skill.category }}</span>
        </div>
        <div class="skill-actions">
          <span class="skill-desc">{{ skill.description }}</span>
          <label class="toggle" @click.stop>
            <input
              type="checkbox"
              :checked="skill.enabled"
              @change="handleToggle(skill)"
            />
            <span class="toggle-slider" />
          </label>
        </div>
      </div>

      <div v-if="expandedSkill === skill.name" class="skill-content">
        <div class="skill-meta">
          <span v-if="skill.license">📄 {{ skill.license }}</span>
          <span>📁 {{ skill.path }}</span>
        </div>
        <pre class="skill-md">{{ skill.content }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skills-panel {
  padding: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.panel-header h3 {
  margin: 0;
  font-size: 18px;
}
.panel-header .icon {
  margin-right: 4px;
}

.refresh-btn {
  padding: 6px 16px;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 4px;
  background: var(--bg-secondary, #fff);
  color: var(--text-primary, #303133);
  cursor: pointer;
  font-size: 13px;
}
.refresh-btn:hover { background: var(--bg-tertiary, #f5f7fa); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--text-muted, #909399);
}

.skill-card {
  border: 1px solid var(--border-color, #e4e7ed);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
  transition: all 0.2s;
  background: var(--bg-secondary, #fff);
}
.skill-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.skill-card.disabled { opacity: 0.6; }

.skill-header {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.skill-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-name {
  font-weight: 600;
  font-size: 14px;
}

.skill-category {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}
.skill-category.public {
  background: #e8f5e9;
  color: #4caf50;
}
.skill-category.custom {
  background: #fff3e0;
  color: #ff9800;
}

.skill-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.skill-desc {
  font-size: 13px;
  color: var(--text-secondary, #606266);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toggle {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}
.toggle input { display: none; }
.toggle-slider {
  position: absolute;
  inset: 0;
  background: #c0c4cc;
  border-radius: 11px;
  cursor: pointer;
  transition: 0.3s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  left: 2px;
  top: 2px;
  background: #fff;
  border-radius: 50%;
  transition: 0.3s;
}
.toggle input:checked + .toggle-slider {
  background: #409EFF;
}
.toggle input:checked + .toggle-slider::before {
  transform: translateX(18px);
}

.skill-content {
  padding: 0 16px 16px;
  border-top: 1px solid var(--border-color, #ebeef5);
}

.skill-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-muted, #909399);
  padding: 8px 0;
}

.skill-md {
  background: var(--bg-tertiary, #f5f7fa);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--text-secondary, #303133);
}
</style>
