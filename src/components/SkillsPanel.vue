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
.skills-panel {
  --card-radius: 12px;
  --card-bg: rgba(255, 255, 255, 0.02);
  --card-border: rgba(255, 255, 255, 0.08);
  --card-border-hover: rgba(99, 102, 241, 0.45);
  --muted: var(--text-muted, #909399);
  --fg: var(--text-primary, #e5e7eb);
  --fg-dim: var(--text-secondary, #a1a1aa);
}

/* Light theme overrides so cards still look clean on white backgrounds. */
:global(:root:not(.dark)) .skills-panel {
  --card-bg: #ffffff;
  --card-border: #e4e7ed;
  --card-border-hover: #6366f1;
  --fg: #303133;
  --fg-dim: #606266;
}

/* ── Hero ── */
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--card-border);
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.hero-text { min-width: 0; }
.hero-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--fg);
  line-height: 1.25;
}
.hero-sub {
  margin: 0;
  color: var(--fg-dim);
  font-size: 13px;
  max-width: 640px;
  line-height: 1.5;
}
.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 10px;
  color: var(--muted);
  pointer-events: none;
}
.search-input {
  height: 34px;
  padding: 0 12px 0 32px;
  border: 1px solid var(--card-border);
  border-radius: 8px;
  background: var(--card-bg);
  color: var(--fg);
  font-size: 13px;
  width: 240px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.search-input:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}
.refresh-btn {
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--card-border);
  border-radius: 8px;
  background: var(--card-bg);
  color: var(--fg);
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.refresh-btn:hover:not(:disabled) {
  border-color: var(--card-border-hover);
}
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Tabs ── */
.tab-strip {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--card-border);
  margin-bottom: 14px;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  background: transparent;
  color: var(--fg-dim);
  font-size: 13px;
  cursor: pointer;
  position: relative;
  transition: color 0.15s;
}
.tab:hover { color: var(--fg); }
.tab.active { color: var(--fg); font-weight: 600; }
.tab.active::after {
  content: '';
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: -1px;
  height: 2px;
  background: #6366f1;
  border-radius: 2px;
}
.tab-count {
  font-size: 11px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}
:global(:root:not(.dark)) .tab-count {
  background: #f0f2f5;
}

/* ── Category chips (primary filter) ── */
.chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

/* ── Sort pills (secondary, text-only, like WorkBuddy) ── */
.sort-row {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.sort-pill {
  padding: 4px 10px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}
.sort-pill:hover { color: var(--fg); }
.sort-pill.active {
  color: var(--fg);
  background: rgba(99, 102, 241, 0.12);
  font-weight: 600;
}
:global(:root:not(.dark)) .sort-pill.active {
  background: rgba(99, 102, 241, 0.08);
}
.chip {
  padding: 5px 12px;
  border-radius: 16px;
  border: 1px solid var(--card-border);
  background: transparent;
  color: var(--fg-dim);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover {
  color: var(--fg);
  border-color: var(--card-border-hover);
}
.chip.active {
  color: #fff;
  background: #6366f1;
  border-color: #6366f1;
}

/* ── Empty state ── */
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--muted);
  font-size: 13px;
}

/* ── Marketplace bar / error ── */
.market-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.06);
  border: 1px solid rgba(99, 102, 241, 0.22);
}
.market-hint {
  font-size: 12px;
  color: var(--fg-dim);
  line-height: 1.5;
}
.market-error {
  padding: 10px 14px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  font-size: 12px;
}
:global(:root:not(.dark)) .market-bar {
  background: #eef2ff;
  border-color: #c7d2fe;
}
:global(:root:not(.dark)) .market-error {
  background: #fef2f2;
  border-color: #fecaca;
  color: #b91c1c;
}

/* ── Market-only card accents ── */
.market-card.is-outdated {
  border-color: rgba(245, 158, 11, 0.45);
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.08), var(--card-bg));
}
.status-badge {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.status-installed {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}
.status-outdated {
  background: rgba(245, 158, 11, 0.18);
  color: #f59e0b;
}
.version-tag.old {
  text-decoration: line-through;
  opacity: 0.7;
}
.license-tag {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--muted);
}
:global(:root:not(.dark)) .license-tag {
  background: #f0f2f5;
}
.stat-item.link {
  color: #6366f1;
  text-decoration: none;
}
.stat-item.link:hover { text-decoration: underline; }
.stat-item.src-pill {
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.18);
  color: #4f46e5;
  font-weight: 600;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stat-item.src-pill:hover {
  background: rgba(99, 102, 241, 0.14);
  text-decoration: none;
}

/* Market card install chip — icon-only at rest, expands to show a
   label on hover / when loading. Mirrors the "+ button" pattern used
   by GitHub marketplace + WorkBuddy's skill cards: unobtrusive but
   visually discoverable. */
.install-chip {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 0;
  padding: 0 8px;
  height: 26px;
  min-width: 26px;
  border-radius: 999px;
  border: 1px solid #6366f1;
  background: #6366f1;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  overflow: hidden;
  transition: all 0.18s ease;
  white-space: nowrap;
}
.install-chip-label {
  display: inline-block;
  max-width: 0;
  opacity: 0;
  margin-left: 0;
  overflow: hidden;
  transition: max-width 0.18s ease, opacity 0.18s ease, margin-left 0.18s ease;
  font-size: 12px;
  font-weight: 600;
}
.install-chip:hover:not(:disabled),
.install-chip.is-loading {
  background: #4f46e5;
  border-color: #4f46e5;
  padding-right: 10px;
}
.install-chip:hover:not(:disabled) .install-chip-label,
.install-chip.is-loading .install-chip-label {
  max-width: 80px;
  margin-left: 4px;
  opacity: 1;
}
.install-chip.is-upgrade {
  background: #f59e0b;
  border-color: #f59e0b;
}
.install-chip.is-upgrade:hover:not(:disabled) {
  background: #d97706;
  border-color: #d97706;
}
.install-chip.is-installed {
  background: transparent;
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.5);
  cursor: default;
}
.install-chip.is-installed .install-chip-label {
  max-width: 60px;
  opacity: 1;
  margin-left: 4px;
}
.install-chip:disabled:not(.is-installed) {
  opacity: 0.6;
  cursor: wait;
}
.install-chip.is-loading {
  animation: chip-spin 1s linear infinite;
}
@keyframes chip-spin {
  from { transform: rotate(0deg); }
  50% { transform: rotate(180deg); }
  to { transform: rotate(360deg); }
}

/* Market card tweaks: anchor the absolute chip cleanly and visually
   distinguish already-installed cards with a subtle green border. */
.skill-card.market-card { position: relative; }
/* Installed/outdated accents: dark theme stays on a dark surface so `--fg`
   stays readable; light theme keeps the airy white tint. */
.skill-card.market-card.is-installed {
  border-color: rgba(16, 185, 129, 0.4);
  background: linear-gradient(
    145deg,
    rgba(16, 185, 129, 0.16) 0%,
    rgba(16, 185, 129, 0.05) 55%,
    var(--card-bg) 100%
  );
}
.skill-card.market-card.is-outdated {
  border-color: rgba(245, 158, 11, 0.4);
  background: linear-gradient(
    145deg,
    rgba(245, 158, 11, 0.14) 0%,
    rgba(245, 158, 11, 0.045) 55%,
    var(--card-bg) 100%
  );
}

:global(:root:not(.dark)) .skills-panel .skill-card.market-card.is-installed {
  background: linear-gradient(135deg, #ffffff 0%, rgba(16, 185, 129, 0.07) 100%);
}
:global(:root:not(.dark)) .skills-panel .skill-card.market-card.is-outdated {
  background: linear-gradient(135deg, #fffef8 0%, rgba(245, 158, 11, 0.07) 100%);
}

.stat-item.stat-muted {
  color: #94a3b8;
  font-style: italic;
}

/* ── Grid ── */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1200px) { .skill-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px)  { .skill-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px)  { .skill-grid { grid-template-columns: 1fr; } }

/* ── Card ── */
.skill-card {
  border: 1px solid var(--card-border);
  border-radius: var(--card-radius);
  background: var(--card-bg);
  cursor: pointer;
  transition: border-color 0.15s, transform 0.12s, box-shadow 0.15s;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.skill-card:hover {
  border-color: var(--card-border-hover);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
}
.skill-card.disabled { opacity: 0.55; }
.skill-card.expanded {
  grid-column: 1 / -1;
  transform: none;
  cursor: default;
  border-color: var(--card-border-hover);
}

.card-body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 14px 14px 14px;
}

.icon-box {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 17px;
  letter-spacing: -0.02em;
  user-select: none;
}

.card-content {
  flex: 1;
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  min-width: 0;
}
.skill-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.builtin-badge {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: linear-gradient(135deg, #6366f1, #3b82f6);
  color: #fff;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.category-tag {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--muted);
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
}
.version-tag {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
}
:global(:root:not(.dark)) .category-tag,
:global(:root:not(.dark)) .version-tag {
  background: #f0f2f5;
}

.stats-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}
.stat-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-variant-numeric: tabular-nums;
}
.stat-item svg { flex-shrink: 0; opacity: 0.8; }
.stat-stars { color: #fbbf24; }
.stat-stars svg { opacity: 1; }
.stat-stars .rating-count {
  color: var(--muted);
  margin-left: 2px;
  font-weight: 400;
}
.author-item {
  margin-left: auto;
  opacity: 0.7;
}

.skill-desc {
  margin: 0;
  font-size: 12px;
  color: var(--fg-dim);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.9em;
}

/* ── Toggle ── */
.toggle {
  flex-shrink: 0;
  position: relative;
  width: 34px;
  height: 20px;
  margin-top: 2px;
}
.toggle input { display: none; }
.toggle-slider {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
}
:global(:root:not(.dark)) .toggle-slider { background: #dcdfe6; }
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 16px;
  height: 16px;
  left: 2px;
  top: 2px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}
.toggle input:checked + .toggle-slider {
  background: #10b981;
}
.toggle input:checked + .toggle-slider::before {
  transform: translateX(14px);
}

/* ── Preview ── */
.skill-preview {
  border-top: 1px solid var(--card-border);
  padding: 12px 16px 16px;
  cursor: default;
}
.preview-meta {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 8px;
}

/* ── Rater ── */
.rater {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border-radius: 8px;
  background: rgba(251, 191, 36, 0.06);
  border: 1px solid rgba(251, 191, 36, 0.18);
  flex-wrap: wrap;
}
:global(:root:not(.dark)) .rater {
  background: #fffbeb;
  border-color: #fde68a;
}
.rater-label {
  font-size: 12px;
  color: var(--fg);
  font-weight: 500;
}
.rater-stars {
  display: inline-flex;
  gap: 2px;
}
.star-btn {
  border: none;
  background: transparent;
  padding: 2px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.22);
  transition: color 0.12s, transform 0.1s;
  line-height: 0;
}
:global(:root:not(.dark)) .star-btn { color: #d1d5db; }
.star-btn:hover:not(:disabled) { transform: scale(1.12); }
.star-btn:hover:not(:disabled),
.star-btn.filled { color: #fbbf24; }
/* Hover-preview: lighting up earlier stars while pointer sits on one star */
.rater-stars:hover .star-btn { color: #fbbf24; }
.rater-stars:hover .star-btn:hover ~ .star-btn {
  color: rgba(255, 255, 255, 0.22);
}
:global(:root:not(.dark)) .rater-stars:hover .star-btn:hover ~ .star-btn {
  color: #d1d5db;
}
.star-btn:disabled { cursor: wait; opacity: 0.5; }
.rater-agg {
  font-size: 11px;
  color: var(--muted);
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.preview-md {
  background: rgba(0, 0, 0, 0.25);
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.55;
  max-height: 360px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--fg-dim);
  margin: 0;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
:global(:root:not(.dark)) .preview-md {
  background: #f5f7fa;
}
</style>
