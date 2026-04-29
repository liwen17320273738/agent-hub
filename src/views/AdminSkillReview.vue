<!--
  Admin-only review queue for the Skills marketplace crawler.

  Surfaces the three Phase-2 endpoints as a single screen:
    - GET  /marketplace/pending        → load queue
    - POST /marketplace/approve/{slug} → promote to trusted
    - POST /marketplace/reject/{slug}  → drop
    - POST /marketplace/crawl          → trigger a fresh crawl

  Route guard checks ``authStore.user.role === 'admin'`` and renders
  a friendly "access denied" screen instead of bouncing to login —
  this lets us link the page from shared URLs without confusing
  non-admin users.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useSkillCrawlStore } from '@/stores/skillCrawl'
import {
  fetchMarketplacePending,
  approveMarketplaceEntry,
  rejectMarketplaceEntry,
  type PendingMarketplaceEntry,
} from '@/services/pipelineApi'

const { t } = useI18n()
const authStore = useAuthStore()
const skillCrawl = useSkillCrawlStore()
const { inProgress, crawlStatus, crawlError, crawlAborted } = storeToRefs(skillCrawl)

const isAdmin = computed(() => authStore.user?.role === 'admin')

const pending = ref<PendingMarketplaceEntry[]>([])
const generatedAt = ref<string | null>(null)
const sources = ref<string[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref<Record<string, 'approving' | 'rejecting'>>({})

// Crawl-trigger toolbar — the enable-topic-search switch is deliberately
// opt-in because it expands what the crawler indexes from "our curated
// list" to "anything GitHub users tagged with claude-skill / agent-skill",
// which needs a human review of the spam that comes with that territory.
// Long-running crawl state lives in skillCrawl store so SPA navigation does not drop the request.
const includeTopicSearch = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await fetchMarketplacePending()
    pending.value = res.items ?? []
    generatedAt.value = res.generated_at ?? null
    sources.value = res.sources ?? []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function handleApprove(entry: PendingMarketplaceEntry) {
  busy.value[entry.slug] = 'approving'
  try {
    await approveMarketplaceEntry(entry.slug)
    pending.value = pending.value.filter(p => p.slug !== entry.slug)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    delete busy.value[entry.slug]
  }
}

async function handleReject(entry: PendingMarketplaceEntry) {
  if (!confirm(t('adminReview.confirmReject', { name: entry.name }))) return
  busy.value[entry.slug] = 'rejecting'
  try {
    await rejectMarketplaceEntry(entry.slug)
    pending.value = pending.value.filter(p => p.slug !== entry.slug)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    delete busy.value[entry.slug]
  }
}

async function handleCrawl() {
  error.value = null
  await skillCrawl.startCrawl(includeTopicSearch.value)
}

function formatGeneratedAt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function iconLetter(name: string): string {
  const clean = name.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '').trim()
  if (!clean) return '?'
  const first = clean[0]
  return /[\u4e00-\u9fa5]/.test(first) ? first : first.toUpperCase()
}

function iconStyle(name: string): Record<string, string> {
  // Reuse the SkillsPanel hash-to-HSL trick so the same skill shows
  // the same icon colour in the market and in this review screen.
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  const hue = h % 360
  return {
    background: `linear-gradient(135deg, hsl(${hue}, 70%, 55%), hsl(${(hue + 30) % 360}, 70%, 45%))`,
  }
}

onMounted(() => {
  if (isAdmin.value) load()
})

watch(
  inProgress,
  (running, wasRunning) => {
    if (wasRunning && !running && isAdmin.value) {
      load()
    }
  },
)
</script>

<template>
  <div class="admin-review-page">
    <header class="page-header">
      <div>
        <h1>{{ t('adminReview.title') }}</h1>
        <p class="subtitle">{{ t('adminReview.subtitle') }}</p>
      </div>
    </header>

    <!-- Access gate. Shows friendly 403 instead of a cryptic 401 -->
    <div v-if="!isAdmin" class="denied">
      <div class="denied-icon">🔒</div>
      <h2>{{ t('adminReview.deniedTitle') }}</h2>
      <p>{{ t('adminReview.deniedBody') }}</p>
    </div>

    <template v-else>
      <!-- Toolbar: metadata + crawl trigger -->
      <section class="toolbar">
        <div class="meta">
          <div class="meta-row">
            <span class="meta-label">{{ t('adminReview.lastCrawl') }}</span>
            <span class="meta-value">{{ formatGeneratedAt(generatedAt) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">{{ t('adminReview.sources') }}</span>
            <span class="meta-value">
              <template v-if="sources.length">
                <a
                  v-for="s in sources"
                  :key="s"
                  :href="`https://github.com/${s}`"
                  target="_blank"
                  rel="noopener"
                  class="src-chip"
                >{{ s }}</a>
              </template>
              <span v-else class="muted">{{ t('adminReview.noSources') }}</span>
            </span>
          </div>
        </div>

        <div class="crawl-actions">
          <label class="topic-toggle" :title="t('adminReview.topicSearchHint')">
            <input
              type="checkbox"
              v-model="includeTopicSearch"
              :disabled="inProgress"
            />
            <span>{{ t('adminReview.topicSearch') }}</span>
          </label>
          <button
            class="btn btn-refresh"
            :disabled="loading"
            @click="load"
          >{{ loading ? t('common.loading') : t('adminReview.refresh') }}</button>
          <button
            v-if="inProgress"
            type="button"
            class="btn btn-stop"
            @click="skillCrawl.cancelCrawl()"
          >{{ t('adminReview.crawlCancel') }}</button>
          <button
            v-else
            type="button"
            class="btn btn-crawl"
            @click="handleCrawl"
          >{{ t('adminReview.crawlNow') }}</button>
          <span v-if="inProgress" class="crawl-running-label">
            <span class="spinner" aria-hidden>⟳</span>
            {{ t('adminReview.crawling') }}
          </span>
        </div>
      </section>

      <p v-if="inProgress" class="crawl-bg-hint">{{ t('adminReview.crawlBackgroundHint') }}</p>

      <div v-if="crawlStatus" class="crawl-result" :class="{ 'is-err': !crawlStatus.ok }">
        <strong>{{ crawlStatus.ok ? t('adminReview.crawlOk') : t('adminReview.crawlFail') }}</strong>
        <pre>{{ crawlStatus.summary }}</pre>
      </div>

      <div v-if="error" class="error-banner">{{ error }}</div>
      <div v-if="crawlAborted" class="info-banner">{{ t('adminReview.crawlAborted') }}</div>
      <div v-else-if="crawlError" class="error-banner">{{ crawlError }}</div>

      <!-- Queue body -->
      <div v-if="!pending.length && !loading" class="empty-state">
        <div class="empty-icon">✓</div>
        <h3>{{ t('adminReview.empty') }}</h3>
        <p>{{ t('adminReview.emptyHint') }}</p>
      </div>

      <ul v-else class="review-list">
        <li
          v-for="entry in pending"
          :key="entry.slug"
          class="review-card"
        >
          <div
            class="icon-box"
            :style="iconStyle(entry.name)"
          >{{ iconLetter(entry.name) }}</div>

          <div class="card-main">
            <div class="name-row">
              <span class="name">{{ entry.name }}</span>
              <span class="slug">{{ entry.slug }}</span>
              <span v-if="entry.version" class="chip">v{{ entry.version }}</span>
              <span v-if="entry.license" class="chip license">{{ entry.license }}</span>
              <span v-if="entry.category" class="chip category">{{ entry.category }}</span>
            </div>

            <p class="desc">
              {{ entry.description || t('skills.noDescription') }}
            </p>

            <div class="stats-row">
              <a
                v-if="entry.source_repo"
                :href="`https://github.com/${entry.source_repo}`"
                target="_blank"
                rel="noopener"
                class="stat-link"
              >
                <span class="src-badge">@{{ entry.source_repo }}</span>
              </a>
              <span v-if="entry.source_stars" class="stat">
                ★ {{ entry.source_stars.toLocaleString() }}
              </span>
              <a
                v-if="entry.homepage"
                :href="entry.homepage"
                target="_blank"
                rel="noopener"
                class="stat-link"
              >{{ t('skills.homepage') }} ↗</a>
              <a
                v-if="entry.source_url && entry.source_url.startsWith('http')"
                :href="entry.source_url"
                target="_blank"
                rel="noopener"
                class="stat-link"
              >SKILL.md ↗</a>
            </div>
          </div>

          <div class="actions">
            <button
              class="btn btn-approve"
              :disabled="busy[entry.slug] !== undefined"
              @click="handleApprove(entry)"
            >
              {{ busy[entry.slug] === 'approving'
                  ? t('adminReview.approving')
                  : t('adminReview.approve') }}
            </button>
            <button
              class="btn btn-reject"
              :disabled="busy[entry.slug] !== undefined"
              @click="handleReject(entry)"
            >
              {{ busy[entry.slug] === 'rejecting'
                  ? t('adminReview.rejecting')
                  : t('adminReview.reject') }}
            </button>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.admin-review-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 28px 48px;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}
.page-header .subtitle {
  margin: 4px 0 20px;
  color: var(--el-text-color-secondary, #64748b);
  font-size: 13px;
}

/* ── Access gate ─────────────────────────────── */
.denied {
  text-align: center;
  padding: 64px 24px;
  border-radius: 12px;
  background: var(--el-bg-color-page, #fff);
  border: 1px solid var(--el-border-color-light, #e5e7eb);
}
.denied-icon { font-size: 48px; margin-bottom: 12px; }
.denied h2 { margin: 0 0 8px; font-size: 18px; }
.denied p { color: var(--el-text-color-secondary, #64748b); margin: 0; }

/* ── Toolbar ─────────────────────────────────── */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e5e7eb);
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.meta { display: flex; flex-direction: column; gap: 6px; min-width: 260px; }
.meta-row { display: flex; gap: 10px; font-size: 13px; align-items: center; flex-wrap: wrap; }
.meta-label { color: var(--el-text-color-secondary, #64748b); min-width: 64px; }
.meta-value { color: var(--el-text-color-primary, #1f2937); }
.src-chip {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  text-decoration: none;
  margin-right: 6px;
  display: inline-block;
}
.src-chip:hover { text-decoration: underline; }
.muted { color: var(--el-text-color-placeholder, #9ca3af); font-style: italic; }

.crawl-actions { display: flex; gap: 10px; align-items: center; }
.topic-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular, #374151);
  cursor: pointer;
  user-select: none;
}
.topic-toggle input { margin: 0; }

.btn {
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn:disabled { opacity: 0.6; cursor: wait; }
.btn-refresh {
  background: transparent;
  border-color: var(--el-border-color, #d1d5db);
  color: var(--el-text-color-regular, #374151);
}
.btn-refresh:hover:not(:disabled) { background: var(--el-fill-color-light, #f3f4f6); }
.btn-crawl {
  background: #6366f1;
  color: #fff;
  border-color: #6366f1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-crawl:hover:not(:disabled) { background: #4f46e5; border-color: #4f46e5; }
.btn-stop {
  background: transparent;
  color: #ea580c;
  border-color: rgba(234, 88, 12, 0.5);
}
.btn-stop:hover { background: rgba(234, 88, 12, 0.08); border-color: #ea580c; }
.spinner { display: inline-block; animation: spin 0.8s linear infinite; }
.crawl-bg-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #64748b);
  line-height: 1.5;
}
.crawl-running-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #6366f1;
}
.info-banner {
  padding: 10px 14px;
  margin-bottom: 14px;
  background: rgba(59, 130, 246, 0.08);
  border-left: 3px solid #3b82f6;
  border-radius: 6px;
  color: var(--el-text-color-regular, #1e40af);
  font-size: 13px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.btn-approve {
  background: #10b981;
  color: #fff;
  border-color: #10b981;
}
.btn-approve:hover:not(:disabled) { background: #059669; border-color: #059669; }
.btn-reject {
  background: transparent;
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.4);
}
.btn-reject:hover:not(:disabled) {
  background: rgba(220, 38, 38, 0.08);
  border-color: #dc2626;
}

.crawl-result {
  padding: 10px 14px;
  margin-bottom: 14px;
  background: rgba(16, 185, 129, 0.08);
  border-left: 3px solid #10b981;
  border-radius: 6px;
  font-size: 12px;
}
.crawl-result.is-err {
  background: rgba(220, 38, 38, 0.08);
  border-left-color: #dc2626;
}
.crawl-result pre {
  margin: 6px 0 0;
  white-space: pre-wrap;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--el-text-color-secondary, #64748b);
}

.error-banner {
  padding: 10px 14px;
  margin-bottom: 14px;
  background: rgba(220, 38, 38, 0.08);
  border-left: 3px solid #dc2626;
  border-radius: 6px;
  color: #991b1b;
  font-size: 13px;
}

/* ── Empty state ─────────────────────────────── */
.empty-state {
  text-align: center;
  padding: 64px 24px;
  border-radius: 12px;
  background: var(--el-bg-color, #fff);
  border: 1px dashed var(--el-border-color-light, #e5e7eb);
}
.empty-icon {
  width: 56px; height: 56px;
  margin: 0 auto 12px;
  border-radius: 50%;
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px;
  font-weight: 700;
}
.empty-state h3 { margin: 0 0 6px; font-size: 16px; }
.empty-state p { margin: 0; color: var(--el-text-color-secondary, #64748b); font-size: 13px; }

/* ── Review list ─────────────────────────────── */
.review-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.review-card {
  display: grid;
  grid-template-columns: 48px 1fr auto;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e5e7eb);
  align-items: center;
}
.icon-box {
  width: 48px; height: 48px;
  border-radius: 10px;
  color: #fff;
  font-weight: 700;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-shadow: 0 1px 2px rgba(0,0,0,0.2);
}
.card-main { min-width: 0; }
.name-row {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  margin-bottom: 4px;
}
.name { font-weight: 700; font-size: 15px; color: var(--el-text-color-primary); }
.slug {
  color: var(--el-text-color-secondary, #64748b);
  font-size: 12px;
  font-family: ui-monospace, monospace;
}
.chip {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--el-fill-color-light, #f3f4f6);
  color: var(--el-text-color-regular, #374151);
  line-height: 1.5;
}
.chip.license { background: rgba(59, 130, 246, 0.1); color: #1d4ed8; }
.chip.category { background: rgba(168, 85, 247, 0.1); color: #7e22ce; }

.desc {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--el-text-color-regular, #4b5563);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.stats-row {
  display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px;
  color: var(--el-text-color-secondary, #64748b);
}
.stat-link, .stat { color: var(--el-text-color-secondary); text-decoration: none; }
.stat-link:hover { color: #4f46e5; text-decoration: underline; }
.src-badge {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}

.actions { display: flex; flex-direction: column; gap: 6px; min-width: 96px; }

@media (max-width: 720px) {
  .review-card { grid-template-columns: 40px 1fr; }
  .actions { grid-column: 1 / -1; flex-direction: row; justify-content: flex-end; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .crawl-actions { justify-content: flex-end; }
}
</style>
