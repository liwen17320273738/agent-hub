<script setup lang="ts">
/**
 * SkillsPanel — WorkBuddy-style skill marketplace.
 *
 * Layout follows the reference screenshot:
 *   - hero with title / subtitle on the left, search + primary CTA on the right
 *   - tab strip (All / Enabled / Disabled) + category chip row
 *   - 4-col auto-fit card grid with left icon + right content
 *   - click a card to expand its SKILL.md inline (spanning all columns)
 *
 * The backend today only exposes *installed* skills, so the "recommended /
 * hub / bundles" trichotomy from WorkBuddy is replaced by an
 * enabled/disabled split over the installed set. The visual skeleton stays
 * identical so we can wire a real marketplace later without another redesign.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fetchSkills,
  toggleSkill,
  rateSkill,
  fetchMarketplace,
  refreshMarketplace,
  installMarketplaceSkill,
  type Skill,
  type MarketplaceListing,
} from '@/services/pipelineApi'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

const skills = ref<Skill[]>([])
const marketplace = ref<MarketplaceListing[]>([])
const marketplaceError = ref<string>('')
const installing = ref<Record<string, boolean>>({})
const loading = ref(false)
const loadingMarket = ref(false)
const expandedSkill = ref<string | null>(null)
const keyword = ref('')
type TabKey = 'all' | 'enabled' | 'disabled' | 'market'
const activeTab = ref<TabKey>('all')
const activeCategory = ref<string>('all')
type SortKey = 'default' | 'installs' | 'updated' | 'name'
const sortKey = ref<SortKey>('default')
const sortOptions: { key: SortKey }[] = [
  { key: 'default' },
  { key: 'installs' },
  { key: 'updated' },
  { key: 'name' },
]

async function load() {
  loading.value = true
  try {
    // Always ask for disabled skills too — the UI needs to render the
    // "未启用" tab with them. Without this the tab counter says "3" but
    // the list is empty, which looks broken.
    skills.value = await fetchSkills({ includeDisabled: true })
  } catch {
    skills.value = []
  } finally {
    loading.value = false
  }
}

async function loadMarketplace(force = false) {
  loadingMarket.value = true
  marketplaceError.value = ''
  try {
    if (force) {
      // Fire-and-forget — if refresh errs we still try the listing
      // with a stale cache rather than blocking the user.
      try { await refreshMarketplace() } catch {}
    }
    const res = await fetchMarketplace()
    marketplace.value = res.items || []
    if (res.error) marketplaceError.value = res.error
  } catch (e: unknown) {
    marketplace.value = []
    marketplaceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loadingMarket.value = false
  }
}

// Compact-chip helpers: picking the label + tooltip in TS keeps the
// template clean and gives us one place to localise per install state.
function installChipLabel(listing: MarketplaceListing): string {
  if (installing.value[listing.slug]) return t('skills.installing')
  if (listing.install_state === 'installed') return t('skills.installed')
  if (listing.install_state === 'outdated') return t('skills.upgrade')
  return t('skills.install')
}
function installChipTitle(listing: MarketplaceListing): string {
  if (listing.install_state === 'installed') {
    return t('skills.installedTip', { v: listing.local_version ?? listing.version })
  }
  if (listing.install_state === 'outdated') {
    return t('skills.upgradeTip', {
      from: listing.local_version ?? '—',
      to: listing.version,
    })
  }
  return t('skills.installTip', { v: listing.version })
}

async function handleInstall(listing: MarketplaceListing) {
  if (installing.value[listing.slug]) return
  installing.value[listing.slug] = true
  try {
    const res = await installMarketplaceSkill(listing.slug)
    // Update in place so the button flips to "已安装" without a flicker.
    listing.install_state = 'installed'
    listing.local_version = res.skill.version
    listing.enabled = res.skill.enabled
    // Also refresh installed list so the Skills tabs mirror reality.
    await load()
  } catch (e: unknown) {
    console.error('Install failed:', e)
    marketplaceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    installing.value[listing.slug] = false
  }
}

async function handleToggle(skill: Skill) {
  try {
    // Prefer `id` (stable slug) over `name` (can be CJK/localised).
    // The backend also accepts name as a fallback, but sending id is
    // what lets URL-safe routing work without needing to percent-encode
    // every Chinese character.
    await toggleSkill(skill.id || skill.name, !skill.enabled)
    skill.enabled = !skill.enabled
  } catch (e: unknown) {
    console.error('Toggle skill failed:', e)
  }
}

// Per-card in-flight guards so the 5 star buttons can't fire in parallel
// and produce a thrashy UI when the user scrubs across them.
const ratingBusy = ref<Record<string, boolean>>({})

async function handleRate(skill: Skill, stars: number) {
  const key = skill.id || skill.name
  if (ratingBusy.value[key]) return
  // If the user clicks the same star they already gave, no-op — clearing
  // a rating isn't supported yet (would need DELETE endpoint), so we
  // silently ignore rather than pretending to reset it.
  if (skill.my_rating === stars) return
  ratingBusy.value[key] = true
  const prev = {
    my_rating: skill.my_rating,
    avg_stars: skill.avg_stars,
    rating_count: skill.rating_count,
  }
  try {
    const res = await rateSkill(skill.id || skill.name, stars)
    skill.my_rating = res.my_rating
    skill.avg_stars = res.avg_stars
    skill.rating_count = res.rating_count
  } catch (e: unknown) {
    console.error('Rate skill failed:', e)
    skill.my_rating = prev.my_rating
    skill.avg_stars = prev.avg_stars
    skill.rating_count = prev.rating_count
  } finally {
    ratingBusy.value[key] = false
  }
}

function toggleExpand(name: string) {
  expandedSkill.value = expandedSkill.value === name ? null : name
}

// Categories come directly from the data — we don't hardcode them so new
// skill types (`devops`, `data`, …) light up automatically.
// Categories are derived from whichever list the user is currently
// looking at — the installed tab shows counts from ``skills``, the
// market tab shows counts from ``marketplace``. Keeping a single
// computed means the chip row updates instantly on tab switch.
const categories = computed(() => {
  const source = activeTab.value === 'market'
    ? marketplace.value.map(l => ({ category: l.category }))
    : skills.value
  const map = new Map<string, number>()
  for (const s of source) {
    const c = (s.category || 'general').toLowerCase()
    map.set(c, (map.get(c) || 0) + 1)
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id, count]) => ({ id, count }))
})

const filteredSkills = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const list = skills.value.filter(s => {
    if (activeTab.value === 'enabled' && !s.enabled) return false
    if (activeTab.value === 'disabled' && s.enabled) return false
    if (activeCategory.value !== 'all' && (s.category || 'general').toLowerCase() !== activeCategory.value) {
      return false
    }
    if (!kw) return true
    return (
      s.name.toLowerCase().includes(kw) ||
      (s.description || '').toLowerCase().includes(kw) ||
      (s.category || '').toLowerCase().includes(kw) ||
      (s.tags || []).some(tag => tag.toLowerCase().includes(kw))
    )
  })

  const sorted = [...list]
  switch (sortKey.value) {
    case 'installs':
      sorted.sort((a, b) => (b.install_count || 0) - (a.install_count || 0))
      break
    case 'updated':
      sorted.sort((a, b) => {
        const ta = a.updated_at ? Date.parse(a.updated_at) : 0
        const tb = b.updated_at ? Date.parse(b.updated_at) : 0
        return tb - ta
      })
      break
    case 'name':
      sorted.sort((a, b) => a.name.localeCompare(b.name))
      break
    // 'default' = backend order (sort_order desc, install_count desc, name asc)
  }
  return sorted
})

// Market tab has its own filter pipeline. The data shape is different
// (``MarketplaceListing`` instead of ``Skill``) and the interesting
// sort dimensions are GitHub stars + freshness, not install count.
const filteredMarketplace = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const list = marketplace.value.filter(l => {
    if (activeCategory.value !== 'all'
        && (l.category || 'general').toLowerCase() !== activeCategory.value) {
      return false
    }
    if (!kw) return true
    return (
      l.name.toLowerCase().includes(kw) ||
      (l.description || '').toLowerCase().includes(kw) ||
      (l.source_repo || '').toLowerCase().includes(kw) ||
      (l.tags || []).some(t => t.toLowerCase().includes(kw))
    )
  })

  const sorted = [...list]
  switch (sortKey.value) {
    case 'installs':  // reuse the "下载量" pill as "stars" in market context
      sorted.sort((a, b) => (b.source_stars || 0) - (a.source_stars || 0))
      break
    case 'updated':
      // No per-entry timestamp from GitHub trees without extra API
      // calls, so fall back to version-lexical sort which at least
      // groups "newer semver" together for readable output.
      sorted.sort((a, b) => (b.version || '').localeCompare(a.version || ''))
      break
    case 'name':
      sorted.sort((a, b) => a.name.localeCompare(b.name))
      break
    // 'default' = stars desc to surface the most-starred repos first.
    default:
      sorted.sort((a, b) => (b.source_stars || 0) - (a.source_stars || 0))
  }
  return sorted
})

const enabledCount = computed(() => skills.value.filter(s => s.enabled).length)

// Colour families map skill.category onto a stable palette so, e.g.,
// every `security` skill shares the same icon chroma. Falls back to a
// hashed colour from the skill name for unknown categories.
const CATEGORY_HUES: Record<string, number> = {
  development: 215, // blue
  engineering: 215,
  product: 265,     // violet
  architecture: 280,
  analysis: 190,    // cyan
  data: 190,
  testing: 30,      // amber
  qa: 30,
  security: 0,      // red
  operations: 160,  // green-cyan
  devops: 160,
  finance: 135,     // green
  design: 310,      // pink
  marketing: 335,
  general: 230,
}

function hueFromString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) >>> 0
  }
  return h % 360
}

function iconStyle(skill: Skill) {
  const cat = (skill.category || 'general').toLowerCase()
  const hue = CATEGORY_HUES[cat] ?? hueFromString(skill.name)
  return {
    background: `linear-gradient(135deg, hsl(${hue}, 70%, 55%), hsl(${(hue + 30) % 360}, 70%, 45%))`,
  }
}

function iconLetter(name: string): string {
  const clean = name.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '').trim()
  if (!clean) return '?'
  // For CJK names show the first character; for ASCII show the first letter.
  const first = clean[0]
  return /[\u4e00-\u9fa5]/.test(first) ? first : first.toUpperCase()
}

// Format install count like WorkBuddy's "↓ 510k": compact, no extra noise.
function formatCount(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return (n / 1000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, '') + 'k'
  return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
}

function relativeUpdated(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - Date.parse(iso)
  if (isNaN(ms) || ms < 0) return ''
  if (ms < 60_000) return t('taskTable.justNow')
  if (ms < 3_600_000) return t('taskTable.minutesAgo', { n: Math.floor(ms / 60_000) })
  if (ms < 86_400_000) return t('taskTable.hoursAgo', { n: Math.floor(ms / 3_600_000) })
  if (ms < 30 * 86_400_000) return t('taskTable.daysAgo', { n: Math.floor(ms / 86_400_000) })
  const d = new Date(iso)
  return d.toLocaleDateString(appLocaleToBcp47(locale.value), { year: 'numeric', month: '2-digit' })
}

// Lazy-load marketplace only when the tab actually becomes active —
// no point hammering GitHub on mount for users who never open it.
watch(activeTab, (tab) => {
  if (tab === 'market' && marketplace.value.length === 0 && !loadingMarket.value) {
    loadMarketplace()
  }
})

onMounted(load)
</script>

<template>
  <div class="skills-panel">
    <!-- ── Hero ── -->
    <header class="hero">
      <div class="hero-text">
        <h1 class="hero-title">
          <slot name="page-title">{{ t('skills.title') }}</slot>
        </h1>
        <p class="hero-sub">
          <slot name="page-subtitle">{{ t('skills.pageSubtitle') }}</slot>
        </p>
      </div>
      <div class="hero-actions">
        <div class="search-wrap">
          <svg class="search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7"></circle>
            <path d="m21 21-4.3-4.3"></path>
          </svg>
          <input
            v-model="keyword"
            type="text"
            :placeholder="t('skills.searchPlaceholder')"
            class="search-input"
          />
        </div>
        <button class="refresh-btn" @click="load" :disabled="loading" :title="t('skills.refresh')">
          {{ loading ? t('skills.refreshing') : t('skills.refresh') }}
        </button>
      </div>
    </header>

    <!-- ── Tabs ── -->
    <div class="tab-strip">
      <button
        :class="['tab', { active: activeTab === 'all' }]"
        @click="activeTab = 'all'"
      >
        {{ t('inbox.all') }}<span class="tab-count">{{ skills.length }}</span>
      </button>
      <button
        :class="['tab', { active: activeTab === 'enabled' }]"
        @click="activeTab = 'enabled'"
      >
        {{ t('skills.tabEnabled') }}<span class="tab-count">{{ enabledCount }}</span>
      </button>
      <button
        :class="['tab', { active: activeTab === 'disabled' }]"
        @click="activeTab = 'disabled'"
      >
        {{ t('skills.tabDisabled') }}<span class="tab-count">{{ skills.length - enabledCount }}</span>
      </button>
      <button
        :class="['tab', 'tab-market', { active: activeTab === 'market' }]"
        @click="activeTab = 'market'"
      >
        {{ t('skills.tabMarket') }}
        <span v-if="marketplace.length" class="tab-count">{{ marketplace.length }}</span>
      </button>
    </div>

    <!-- ── Category chips ── Shown for all tabs, including market.
         For market the chips are derived from marketplace listings. -->
    <div v-if="categories.length" class="chip-row">
      <button
        :class="['chip', { active: activeCategory === 'all' }]"
        @click="activeCategory = 'all'"
      >
        {{ t('inbox.all') }}
      </button>
      <button
        v-for="c in categories"
        :key="c.id"
        :class="['chip', { active: activeCategory === c.id }]"
        @click="activeCategory = c.id"
      >
        {{ c.id }}
      </button>
    </div>

    <!-- ── Sort pills ── Same pills for market tab; the computed
         sort pipeline maps "installs" → stars when in market mode. -->
    <div class="sort-row">
      <button
        v-for="opt in sortOptions"
        :key="opt.key"
        :class="['sort-pill', { active: sortKey === opt.key }]"
        @click="sortKey = opt.key"
      >
        {{ activeTab === 'market'
            ? t(`skills.sort.market_${opt.key}`)
            : t(`skills.sort.${opt.key}`) }}
      </button>
    </div>

    <!-- ── Marketplace notice bar ── -->
    <div v-if="activeTab === 'market'" class="market-bar">
      <span class="market-hint">
        {{ t('skills.marketHint') }}
      </span>
      <button
        class="refresh-btn"
        @click="loadMarketplace(true)"
        :disabled="loadingMarket"
      >
        {{ loadingMarket ? t('skills.refreshing') : t('skills.refresh') }}
      </button>
    </div>
    <div v-if="activeTab === 'market' && marketplaceError" class="market-error">
      {{ t('skills.marketError', { error: marketplaceError }) }}
    </div>

    <!-- ── Empty states ── -->
    <template v-if="activeTab !== 'market'">
      <div v-if="!skills.length && !loading" class="empty-state">
        {{ t('skills.empty') }}
      </div>
      <div v-else-if="!filteredSkills.length" class="empty-state">
        {{ t('skills.noMatch') }}
      </div>
    </template>
    <template v-else>
      <div v-if="!marketplace.length && !loadingMarket" class="empty-state">
        {{ marketplaceError ? t('skills.marketEmptyError') : t('skills.marketEmpty') }}
      </div>
    </template>

    <!-- ── Marketplace grid (WorkBuddy-compact layout) ──
         Structure mirrors the installed-tab card: icon left, content
         right, floating corner action button. The action morphs
         between install / upgrade / already-installed based on
         ``install_state``, and the stats row surfaces the provenance
         badge + star count so users recognise the source at a glance. -->
    <div
      v-if="activeTab === 'market' && filteredMarketplace.length"
      class="skill-grid"
    >
      <article
        v-for="listing in filteredMarketplace"
        :key="listing.slug"
        class="skill-card market-card"
        :class="{
          'is-outdated': listing.install_state === 'outdated',
          'is-installed': listing.install_state === 'installed',
        }"
      >
        <div class="card-body">
          <div class="icon-box" :style="iconStyle({
            name: listing.name,
            category: listing.category,
          } as Skill)">
            {{ iconLetter(listing.name) }}
          </div>
          <div class="card-content">
            <div class="title-row">
              <span class="skill-name" :title="listing.name">{{ listing.name }}</span>
              <span
                v-if="listing.install_state === 'outdated'"
                class="status-badge status-outdated"
              >{{ t('skills.outdated') }}</span>
              <span
                v-else-if="listing.install_state === 'installed'"
                class="status-badge status-installed"
              >{{ t('skills.installed') }}</span>
            </div>
            <p class="skill-desc">
              {{ listing.description || t('skills.noDescription') }}
            </p>
            <div class="stats-row">
              <!-- Provenance badge is the single most informative
                   signal on a market card (official anthropics/skills
                   vs some random fork), so it always renders first. -->
              <a
                v-if="listing.source_repo"
                :href="`https://github.com/${listing.source_repo}`"
                target="_blank"
                rel="noopener"
                class="stat-item link src-pill"
                :title="t('skills.sourceRepo', { repo: listing.source_repo })"
                @click.stop
              >
                <svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor" aria-hidden>
                  <path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2.3c-3.3.7-4-1.4-4-1.4-.6-1.4-1.4-1.8-1.4-1.8-1.1-.8.1-.8.1-.8 1.2.1 1.9 1.3 1.9 1.3 1.1 1.9 2.9 1.4 3.6 1 .1-.8.4-1.4.8-1.7-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .3"/>
                </svg>
                {{ listing.source_repo }}
              </a>
              <span
                v-if="listing.source_stars && listing.source_stars > 0"
                class="stat-item"
                :title="t('skills.stars', { n: listing.source_stars })"
              >
                ★ {{ formatCount(listing.source_stars) }}
              </span>
              <span class="stat-item">v{{ listing.version }}</span>
              <span
                v-if="listing.install_state === 'outdated' && listing.local_version"
                class="stat-item stat-muted"
                :title="t('skills.localVersion', { v: listing.local_version })"
              >← v{{ listing.local_version }}</span>
            </div>
          </div>

          <!-- Corner install chip: icon-only in the default state so
               the card stays compact, widens on hover/loading. -->
          <button
            class="install-chip"
            :class="{
              'is-upgrade': listing.install_state === 'outdated',
              'is-installed': listing.install_state === 'installed',
              'is-loading': installing[listing.slug],
            }"
            :disabled="installing[listing.slug] || listing.install_state === 'installed'"
            :title="installChipTitle(listing)"
            @click.stop="handleInstall(listing)"
          >
            <template v-if="installing[listing.slug]">⟳</template>
            <template v-else-if="listing.install_state === 'installed'">✓</template>
            <template v-else-if="listing.install_state === 'outdated'">↑</template>
            <template v-else>+</template>
            <span class="install-chip-label">{{ installChipLabel(listing) }}</span>
          </button>
        </div>
      </article>
    </div>

    <!-- ── Card grid (installed) ── -->
    <div
      v-if="activeTab !== 'market' && filteredSkills.length"
      class="skill-grid"
    >
      <article
        v-for="skill in filteredSkills"
        :key="skill.name"
        class="skill-card"
        :class="{ disabled: !skill.enabled, expanded: expandedSkill === skill.name }"
        @click="toggleExpand(skill.name)"
      >
        <div class="card-body">
          <div class="icon-box" :style="iconStyle(skill)">
            {{ iconLetter(skill.name) }}
          </div>
          <div class="card-content">
            <div class="title-row">
              <span class="skill-name" :title="skill.name">{{ skill.name }}</span>
              <span
                v-if="skill.is_builtin"
                class="builtin-badge"
                :title="t('skills.builtinTip')"
              >{{ t('skills.builtin') }}</span>
            </div>
            <div class="meta-row">
              <span class="category-tag">{{ skill.category || 'general' }}</span>
              <span v-if="skill.version" class="version-tag">v{{ skill.version }}</span>
            </div>
            <p class="skill-desc">
              {{ skill.description || t('skills.noDescription') }}
            </p>
            <div class="stats-row">
              <span
                v-if="skill.install_count > 0"
                class="stat-item"
                :title="t('skills.installCount', { n: skill.install_count })"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2">
                  <path d="M12 3v12m0 0 5-5m-5 5-5-5"/>
                  <path d="M4 21h16"/>
                </svg>
                {{ formatCount(skill.install_count) }}
              </span>
              <span
                v-if="skill.rating_count > 0"
                class="stat-item stat-stars"
                :title="t('skills.ratingTooltip', {
                  avg: skill.avg_stars.toFixed(1),
                  n: skill.rating_count,
                })"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
                  <path d="M12 2l2.9 6.9 7.1.6-5.4 4.7 1.7 7L12 17.3 5.7 21.2l1.7-7L2 9.5l7.1-.6L12 2z"/>
                </svg>
                {{ skill.avg_stars.toFixed(1) }}
                <span class="rating-count">({{ formatCount(skill.rating_count) }})</span>
              </span>
              <span v-if="relativeUpdated(skill.updated_at)" class="stat-item" :title="skill.updated_at || ''">
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2">
                  <circle cx="12" cy="12" r="9"/>
                  <path d="M12 7v5l3 2"/>
                </svg>
                {{ relativeUpdated(skill.updated_at) }}
              </span>
              <span v-if="skill.author && skill.author !== 'system'" class="stat-item author-item" :title="t('skills.author')">
                @{{ skill.author }}
              </span>
            </div>
          </div>
          <label class="toggle" @click.stop>
            <input
              type="checkbox"
              :checked="skill.enabled"
              @change="handleToggle(skill)"
            />
            <span class="toggle-slider" />
          </label>
        </div>

        <!-- Inline markdown preview — expanded card spans the whole row. -->
        <div v-if="expandedSkill === skill.name" class="skill-preview" @click.stop>
          <div class="preview-meta">
            <span>v{{ skill.version }}</span>
            <span v-if="skill.author">by {{ skill.author }}</span>
            <span v-if="skill.tags?.length">🏷 {{ skill.tags.join(', ') }}</span>
          </div>

          <!-- Rater: 5 clickable stars. my_rating drives the fill. -->
          <div class="rater">
            <span class="rater-label">
              {{ skill.my_rating
                ? t('skills.yourRating', { n: skill.my_rating })
                : t('skills.rateThis') }}
            </span>
            <div class="rater-stars" :aria-busy="!!ratingBusy[skill.id || skill.name]">
              <button
                v-for="n in 5"
                :key="n"
                class="star-btn"
                :class="{ filled: n <= skill.my_rating }"
                :disabled="!!ratingBusy[skill.id || skill.name]"
                :aria-label="`${n} / 5`"
                @click="handleRate(skill, n)"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                  <path d="M12 2l2.9 6.9 7.1.6-5.4 4.7 1.7 7L12 17.3 5.7 21.2l1.7-7L2 9.5l7.1-.6L12 2z"/>
                </svg>
              </button>
            </div>
            <span v-if="skill.rating_count" class="rater-agg">
              {{ t('skills.ratingAvg', {
                avg: skill.avg_stars.toFixed(1),
                n: skill.rating_count,
              }) }}
            </span>
          </div>

          <pre class="preview-md">{{ skill.content || t('skills.noContent') }}</pre>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
@import "./SkillsPanel.css";
</style>
