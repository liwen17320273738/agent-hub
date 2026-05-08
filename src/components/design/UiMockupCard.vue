<template>
  <div class="ui-mockup-view">
    <!-- Image mockup -->
    <div v-if="imagePath" class="mockup-section">
      <div class="section-header">
        <span class="section-icon">🖼️</span>
        <span>UI 设计稿</span>
      </div>
      <div class="image-preview" @click="openImage">
        <img :src="imagePath" alt="UI Mockup" />
        <div class="image-overlay">
          <span class="overlay-text">点击查看大图</span>
        </div>
      </div>
    </div>

    <!-- HTML prototype -->
    <div v-if="htmlPath" class="mockup-section">
      <div class="section-header">
        <span class="section-icon">🖌️</span>
        <span>可交互原型</span>
        <a :href="htmlPath" target="_blank" class="open-link">在新窗口打开 ↗</a>
      </div>
      <iframe
        v-if="htmlPath"
        :src="htmlPath"
        class="prototype-frame"
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
      />
    </div>

    <!-- Design spec -->
    <div class="mockup-section">
      <div class="section-header">
        <span class="section-icon">📋</span>
        <span>设计规范</span>
      </div>
      <div class="spec-content">
        <pre>{{ specText }}</pre>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!imagePath && !htmlPath" class="empty-state">
      <div class="empty-icon">🎨</div>
      <p class="empty-title">暂无设计稿</p>
      <p class="empty-desc">当前阶段还未生成 UI 设计稿，Pipeline 执行 design 阶段后将自动生成</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch } from '@/services/api'

const props = defineProps<{
  taskId: string
}>()

const imagePath = ref('')
const htmlPath = ref('')
const specText = ref('')

onMounted(async () => {
  try {
    // Fetch mockup artifacts
    const result = await apiFetch(`/pipeline/tasks/${props.taskId}/artifacts`)
    if (result.ok && result.artifacts) {
      for (const art of result.artifacts) {
        if (art.artifactType === 'ui_mockup' && art.isLatest) {
          imagePath.value = art.metadata?.filePath || ''
        }
        if (art.artifactType === 'ui_mockup_html' && art.isLatest) {
          htmlPath.value = art.metadata?.filePath || ''
        }
        if (art.artifactType === 'ui_spec' && art.isLatest) {
          specText.value = art.content || ''
        }
      }
    }
  } catch (err) {
    console.error('[ui-mockup] fetch error:', err)
  }
})

function openImage() {
  if (imagePath.value) {
    window.open(imagePath.value, '_blank')
  }
}
</script>

<style scoped>
.ui-mockup-view {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 8px;
}

.mockup-section {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 14px;
  font-weight: 500;
}

.section-icon {
  font-size: 18px;
}

.open-link {
  margin-left: auto;
  color: #818cf8;
  text-decoration: none;
  font-size: 13px;
  font-weight: 400;
}

.open-link:hover {
  text-decoration: underline;
}

.image-preview {
  position: relative;
  cursor: pointer;
  overflow: hidden;
}

.image-preview img {
  width: 100%;
  max-height: 500px;
  object-fit: contain;
  display: block;
  background: #0a0a1a;
}

.image-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;
}

.image-preview:hover .image-overlay {
  background: rgba(0, 0, 0, 0.4);
}

.overlay-text {
  color: #fff;
  font-size: 14px;
  opacity: 0;
  transition: opacity 0.3s;
  padding: 8px 16px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.5);
}

.image-preview:hover .overlay-text {
  opacity: 1;
}

.prototype-frame {
  width: 100%;
  height: 600px;
  border: none;
  background: #fff;
}

.spec-content {
  padding: 20px;
  max-height: 400px;
  overflow-y: auto;
}

.spec-content pre {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.8);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  max-width: 400px;
  margin: 0 auto;
}
</style>
