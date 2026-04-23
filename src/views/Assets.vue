<template>
  <div class="assets-view">
    <h1>资产中心</h1>
    <p class="view-subtitle">模型、技能、MCP 服务器、评测 — 集中管理</p>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="模型" name="models">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/model-lab')">模型实验室</el-button>
        </div>
        <el-empty description="模型管理与测试" />
      </el-tab-pane>

      <el-tab-pane label="技能" name="skills">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/skills')">技能中心</el-button>
        </div>
        <el-empty description="可复用技能包" />
      </el-tab-pane>

      <el-tab-pane label="MCP 服务器" name="mcp">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/mcp-servers')">MCP 管理</el-button>
        </div>
        <el-empty description="外部工具与协议服务器" />
      </el-tab-pane>

      <el-tab-pane label="评测" name="eval">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/eval-lab')">评测实验室</el-button>
        </div>
        <el-empty description="Agent 质量评测" />
      </el-tab-pane>

      <el-tab-pane label="代码索引" name="codebase">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/codebase-lab')">代码索引</el-button>
        </div>
        <el-empty description="代码库检索与分析" />
      </el-tab-pane>

      <el-tab-pane label="观测台" name="observability">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/insights/observability')">Agent 观测台</el-button>
        </div>
        <el-empty description="运行时指标与链路追踪" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const activeTab = ref('models')
</script>

<style scoped>
.assets-view {
  padding: 24px 32px;
  max-width: 1200px;
}

.assets-view h1 {
  font-size: 22px;
  margin-bottom: 4px;
}

.view-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 24px;
}

.asset-action {
  margin-bottom: 16px;
}
</style>
