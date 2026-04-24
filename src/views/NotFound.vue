<template>
  <div class="not-found-page">
    <div class="not-found-content">
      <h1>404</h1>
      <p>{{ t('notFound.text_1') }}</p>
      <router-link to="/" class="back-link">
        <el-button type="primary">{{ t('notFound.text_2') }}</el-button>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>


<style scoped>
.not-found-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}

.not-found-content {
  text-align: center;
}

.not-found-content h1 {
  font-size: 72px;
  font-weight: 700;
  color: var(--text-muted);
  margin: 0 0 8px;
  line-height: 1;
}

.not-found-content p {
  font-size: 18px;
  color: var(--text-secondary);
  margin: 0 0 24px;
}
</style>
