<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { knowledgeApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useUiStore } from '@/stores/ui'
import type { KnowledgeCatalog, KnowledgeItem, Rule } from '@/types'
import { formatNumber } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

type Tab = 'rules' | 'items' | 'rag'

const KIND_META: Record<string, { label: string; tone: string }> = {
  rule: { label: '业务规则', tone: 'blue' },
  hard: { label: '硬约束', tone: 'danger' },
  soft: { label: '软约束', tone: 'warning' },
}

const ui = useUiStore()

const tab = ref<Tab>('rules')
const catalog = ref<KnowledgeCatalog | null>(null)
const items = ref<KnowledgeItem[]>([])
const loading = ref(false)
const itemsLoading = ref(false)
const error = ref('')
const kindFilter = ref('')
const categoryFilter = ref('')
const q = ref('')
const itemCategory = ref('')
const itemQuery = ref('')
const ruleOpen = ref(false)
const activeRule = ref<Rule | null>(null)

const ragQuery = ref('')
const ragLoading = ref(false)
const ragResult = ref<{
  query: string
  items: KnowledgeItem[]
  hits: number
  mode: string
  note: string
} | null>(null)

const allRules = computed<Rule[]>(() => {
  if (!catalog.value) return []
  if (kindFilter.value === 'hard') return catalog.value.hard_constraints
  if (kindFilter.value === 'soft') return catalog.value.soft_constraints
  if (kindFilter.value === 'rule') return catalog.value.rules
  return [...catalog.value.rules, ...catalog.value.hard_constraints, ...catalog.value.soft_constraints]
})

const filteredRules = computed(() => {
  const keyword = q.value.trim().toLowerCase()
  return allRules.value.filter((rule) => {
    if (categoryFilter.value && rule.category !== categoryFilter.value) return false
    if (!keyword) return true
    return `${rule.code} ${rule.title} ${rule.description} ${rule.category}`.toLowerCase().includes(keyword)
  })
})

const categories = computed(() => {
  if (!catalog.value) return []
  const names = new Set<string>()
  for (const rule of [...catalog.value.rules, ...catalog.value.hard_constraints, ...catalog.value.soft_constraints]) {
    if (rule.category) names.add(rule.category)
  }
  return Array.from(names)
})

const itemCategories = computed(() => Array.from(new Set(items.value.map((item) => item.category))))

const filteredItems = computed(() => {
  const keyword = itemQuery.value.trim().toLowerCase()
  return items.value.filter((item) => {
    if (itemCategory.value && item.category !== itemCategory.value) return false
    if (!keyword) return true
    return `${item.code} ${item.title} ${item.content} ${item.tags.join(' ')}`.toLowerCase().includes(keyword)
  })
})

const tabs = computed(() => [
  { key: 'rules' as Tab, label: '规则库', count: catalog.value?.summary.total ?? 0 },
  { key: 'items' as Tab, label: '专识条目', count: items.value.length },
  { key: 'rag' as Tab, label: '本地检索', count: ragResult.value?.hits ?? 0 },
])

function kindMeta(kind: string) {
  return KIND_META[kind] || KIND_META.rule
}

function openRule(rule: Rule) {
  activeRule.value = rule
  ruleOpen.value = true
}

async function loadCatalog() {
  loading.value = true
  error.value = ''
  try {
    catalog.value = await knowledgeApi.catalog()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function loadItems() {
  itemsLoading.value = true
  try {
    const res = await knowledgeApi.items({ limit: 200 })
    items.value = res.items
  } catch (err) {
    ui.error('专识条目加载失败', errorMessage(err))
  } finally {
    itemsLoading.value = false
  }
}

async function runSearch() {
  const query = ragQuery.value.trim()
  if (!query) {
    ui.warning('请输入检索问题')
    return
  }
  ragLoading.value = true
  try {
    ragResult.value = await knowledgeApi.search(query, 8)
  } catch (err) {
    ui.error('知识检索失败', errorMessage(err))
  } finally {
    ragLoading.value = false
  }
}

function selectRuleExample(text: string) {
  ragQuery.value = text
  tab.value = 'rag'
  runSearch()
}

onMounted(async () => {
  await Promise.all([loadCatalog(), loadItems()])
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L5 · 知识规则基座"
      title="规则与专识中心"
      subtitle="68 条排产规则 · HC-01~14 硬约束 · SC-01~13 软约束 · 全量条目可溯源"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="loadCatalog">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button class="btn btn-primary" type="button" @click="tab = 'rag'">
          <AppIcon name="spark" :size="15" />
          本地检索
        </button>
      </template>
      <template #meta>
        <span>启用规则 {{ catalog?.summary.enabled ?? '—' }}</span>
        <span class="meta-dot" />
        <span>专识 {{ formatNumber(catalog?.summary.knowledge_items) }} 条</span>
        <span class="meta-dot" />
        <span>一期专识 {{ formatNumber(catalog?.summary.dataset_scale.expert) }} 条</span>
      </template>
    </PageHeader>

    <div class="k-stats">
      <div class="k-stat panel">
        <span>排产规则</span>
        <strong class="num">{{ catalog?.summary.rules ?? '—' }}</strong>
        <small>业务规则全集</small>
      </div>
      <div class="k-stat panel tone-danger">
        <span>硬约束</span>
        <strong class="num">{{ catalog?.summary.hard ?? '—' }}</strong>
        <small>HC-01 ~ HC-14</small>
      </div>
      <div class="k-stat panel tone-warning">
        <span>软约束</span>
        <strong class="num">{{ catalog?.summary.soft ?? '—' }}</strong>
        <small>SC-01 ~ SC-13</small>
      </div>
      <div class="k-stat panel tone-teal">
        <span>专识知识库</span>
        <strong class="num">{{ formatNumber(catalog?.summary.knowledge_items) }}</strong>
        <small>可检索 · 可溯源</small>
      </div>
      <div class="k-stat panel">
        <span>通识数据</span>
        <strong class="num">{{ formatNumber(catalog?.summary.dataset_scale.general) }}</strong>
        <small>T1~T5 + M</small>
      </div>
    </div>

    <div class="tabs-row">
      <div class="segmented">
        <button
          v-for="item in tabs"
          :key="item.key"
          type="button"
          :class="{ active: tab === item.key }"
          @click="tab = item.key"
        >
          {{ item.label }} <span class="tab-count">{{ item.count }}</span>
        </button>
      </div>
    </div>

    <div v-if="error" class="empty">
      <AppIcon name="alert" :size="22" />
      {{ error }}
    </div>

    <template v-else-if="tab === 'rules'">
      <section class="panel">
        <div class="panel-head rule-head">
          <div class="segmented kind-seg">
            <button type="button" :class="{ active: !kindFilter }" @click="kindFilter = ''">
              全部 <span class="tab-count">{{ catalog?.summary.total ?? 0 }}</span>
            </button>
            <button type="button" :class="{ active: kindFilter === 'rule' }" @click="kindFilter = 'rule'">
              业务规则 <span class="tab-count">{{ catalog?.summary.rules ?? 0 }}</span>
            </button>
            <button type="button" :class="{ active: kindFilter === 'hard' }" @click="kindFilter = 'hard'">
              硬约束 <span class="tab-count">{{ catalog?.summary.hard ?? 0 }}</span>
            </button>
            <button type="button" :class="{ active: kindFilter === 'soft' }" @click="kindFilter = 'soft'">
              软约束 <span class="tab-count">{{ catalog?.summary.soft ?? 0 }}</span>
            </button>
          </div>
          <div class="toolbar">
            <select v-model="categoryFilter" class="select category-select">
              <option value="">全部分类</option>
              <option v-for="name in categories" :key="name" :value="name">{{ name }}</option>
            </select>
            <div class="search-box">
              <AppIcon name="search" :size="14" />
              <input v-model="q" class="input" placeholder="规则编号 / 标题 / 描述" />
            </div>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table rule-table">
            <thead>
              <tr>
                <th>编号</th>
                <th>类型</th>
                <th>分类</th>
                <th>规则名称</th>
                <th>优先级</th>
                <th>权重</th>
                <th>适用域</th>
                <th>命中</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in filteredRules" :key="rule.code" class="click-row" @click="openRule(rule)">
                <td class="mono rule-code">{{ rule.code }}</td>
                <td>
                  <span class="badge" :class="`badge-${kindMeta(rule.kind).tone}`">{{ kindMeta(rule.kind).label }}</span>
                </td>
                <td>{{ rule.category }}</td>
                <td class="cell-strong">{{ rule.title }}</td>
                <td class="num">{{ rule.priority }}</td>
                <td class="num">{{ rule.weight }}</td>
                <td>{{ rule.domain || '全域' }}</td>
                <td class="num">{{ rule.hits }}</td>
                <td>
                  <span class="badge" :class="rule.enabled ? 'badge-success' : 'badge-muted'">
                    <span class="dot" />{{ rule.enabled ? '启用' : '停用' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!filteredRules.length" class="empty">未找到匹配规则</div>
        <div class="panel-foot">共 {{ filteredRules.length }} 条规则 · 点击任意行查看触发条件与执行动作</div>
      </section>
    </template>

    <template v-else-if="tab === 'items'">
      <section class="panel">
        <div class="panel-head items-head">
          <div class="segmented category-seg">
            <button type="button" :class="{ active: !itemCategory }" @click="itemCategory = ''">
              全部 <span class="tab-count">{{ items.length }}</span>
            </button>
            <button
              v-for="name in itemCategories"
              :key="name"
              type="button"
              :class="{ active: itemCategory === name }"
              @click="itemCategory = name"
            >
              {{ name }}
            </button>
          </div>
          <div class="search-box">
            <AppIcon name="search" :size="14" />
            <input v-model="itemQuery" class="input" placeholder="搜索专识条目" />
          </div>
        </div>

        <div v-if="itemsLoading" class="k-loading"><span class="spinner" /> 正在加载专识条目…</div>
        <div v-else-if="filteredItems.length" class="item-grid">
          <article v-for="item in filteredItems" :key="item.id" class="item-card">
            <div class="item-head">
              <span class="item-code mono">{{ item.code }}</span>
              <span class="badge badge-muted">{{ item.category }}</span>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.content }}</p>
            <div class="item-tags">
              <span v-for="tag in item.tags.slice(0, 4)" :key="tag" class="item-tag">{{ tag }}</span>
            </div>
            <div class="item-foot">
              <span class="mono">{{ item.source_ref }}</span>
              <span class="confidence">
                <i :style="{ width: `${item.confidence * 100}%` }" />
                置信度 {{ Math.round(item.confidence * 100) }}%
              </span>
            </div>
            <span class="item-version mono">{{ item.trace_version }}</span>
          </article>
        </div>
        <div v-else class="empty">未找到匹配的专识条目</div>
      </section>
    </template>

    <template v-else>
      <section class="rag-panel panel">
        <div class="rag-hero">
          <span class="rag-eyebrow">LOCAL KEYWORD RETRIEVAL · 可溯源</span>
          <h2>用自然语言检索排产知识</h2>
          <p>本地检索，多词加权匹配规则与专识条目，不依赖外部向量服务；所有结果携带 source_ref / trace_version，可回查原始依据。</p>
          <div class="rag-search">
            <div class="search-box">
              <AppIcon name="search" :size="16" />
              <input
                v-model="ragQuery"
                class="input"
                placeholder="例如：瓶颈设备冲突时如何调整排产？"
                @keydown.enter="runSearch"
              />
            </div>
            <button class="btn btn-primary" type="button" :disabled="ragLoading" @click="runSearch">
              <span v-if="ragLoading" class="spinner" />
              <AppIcon v-else name="spark" :size="15" />
              {{ ragLoading ? '检索中…' : '检索' }}
            </button>
          </div>
          <div class="rag-examples">
            <span class="muted">试试：</span>
            <button type="button" class="chip" @click="selectRuleExample('交期优先 军品 保供')">交期优先 · 军品保供</button>
            <button type="button" class="chip" @click="selectRuleExample('瓶颈设备 负荷 均衡')">瓶颈设备 · 负荷均衡</button>
            <button type="button" class="chip" @click="selectRuleExample('换型 成本 优化')">换型成本优化</button>
            <button type="button" class="chip" @click="selectRuleExample('齐套 缺料 开工')">齐套缺料 · 开工阻断</button>
          </div>
        </div>

        <div v-if="ragResult" class="rag-results">
          <div class="rag-meta">
            <span class="badge badge-teal"><span class="dot" />{{ ragResult.mode }}</span>
            <span class="muted">{{ ragResult.hits }} 条结果 · {{ ragResult.note }}</span>
          </div>
          <div v-if="ragResult.items.length" class="rag-list">
            <article v-for="(item, index) in ragResult.items" :key="`${item.code}-${index}`" class="rag-item">
              <div class="rag-rank num">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="rag-item-body">
                <div class="rag-item-head">
                  <span class="badge" :class="item.kind === 'rule' ? 'badge-blue' : 'badge-violet'">
                    {{ item.kind === 'rule' ? '规则' : '专识' }}
                  </span>
                  <span class="mono rag-code">{{ item.code }}</span>
                  <span class="rag-score num">{{ item.score }} 分</span>
                </div>
                <h3>{{ item.title }}</h3>
                <p>{{ item.content }}</p>
                <div class="rag-item-foot">
                  <span class="mono">{{ item.source_ref }}</span>
                  <span class="mono">{{ item.trace_version }}</span>
                  <span v-for="tag in item.tags.slice(0, 3)" :key="tag" class="item-tag">{{ tag }}</span>
                </div>
              </div>
            </article>
          </div>
          <div v-else class="empty">未命中相关知识，请尝试更具体的关键词</div>
        </div>
        <div v-else class="rag-placeholder">
          <div class="rag-orbit">
            <AppIcon name="spark" :size="26" />
          </div>
          <span>检索结果将展示命中依据、置信度与溯源版本</span>
        </div>
      </section>
    </template>

    <BaseDrawer
      :model-value="ruleOpen"
      width="560px"
      :title="activeRule ? `${activeRule.code} · ${activeRule.title}` : '规则详情'"
      :subtitle="activeRule ? `${kindMeta(activeRule.kind).label} · ${activeRule.category}` : ''"
      @update:model-value="ruleOpen = false"
    >
      <template v-if="activeRule">
        <div class="rule-badges">
          <span class="badge" :class="`badge-${kindMeta(activeRule.kind).tone}`">{{ kindMeta(activeRule.kind).label }}</span>
          <span class="badge badge-muted">优先级 {{ activeRule.priority }}</span>
          <span class="badge badge-muted">权重 {{ activeRule.weight }}</span>
          <span class="badge" :class="activeRule.enabled ? 'badge-success' : 'badge-muted'">
            {{ activeRule.enabled ? '启用' : '停用' }}
          </span>
        </div>
        <p class="rule-desc">{{ activeRule.description }}</p>
        <h4 class="rule-section">触发条件</h4>
        <div class="code-block">{{ activeRule.trigger || '—' }}</div>
        <h4 class="rule-section">执行动作</h4>
        <div class="code-block">{{ activeRule.action || '—' }}</div>
        <div class="kv"><span class="k">适用制造域</span><span class="v">{{ activeRule.domain || '全域' }}</span></div>
        <div class="kv"><span class="k">规则分类</span><span class="v">{{ activeRule.category }}</span></div>
        <div class="kv"><span class="k">累计命中</span><span class="v num">{{ activeRule.hits }}</span></div>
      </template>
    </BaseDrawer>
  </div>
</template>

<style scoped>
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}

.k-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.k-stat {
  padding: 14px 16px;
  position: relative;
}

.k-stat::before {
  content: '';
  position: absolute;
  left: 0;
  top: 13px;
  bottom: 13px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
}

.k-stat.tone-danger::before {
  background: var(--danger);
}

.k-stat.tone-warning::before {
  background: var(--warning);
}

.k-stat.tone-teal::before {
  background: var(--teal);
}

.k-stat > span {
  font-size: 11px;
  color: var(--text-3);
}

.k-stat strong {
  display: block;
  font-family: var(--font-display);
  font-size: 25px;
  line-height: 1.3;
  color: var(--text);
}

.k-stat small {
  font-size: 10px;
  color: var(--text-3);
}

.tabs-row {
  display: flex;
  margin-bottom: 14px;
}

.tab-count {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.7;
}

.rule-head {
  flex-wrap: wrap;
}

.rule-head .toolbar {
  flex: 1;
  justify-content: flex-end;
}

.category-select {
  width: 160px;
}

.search-box {
  width: 240px;
}

.click-row {
  cursor: pointer;
}

.rule-code {
  color: var(--accent);
  font-size: 11px;
}

.k-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 42px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.items-head {
  flex-wrap: wrap;
}

.items-head .search-box {
  margin-left: auto;
}

.category-seg {
  max-width: 100%;
}

.item-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
}

.item-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 15px 16px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-inset);
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.item-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.item-code {
  font-size: 10.5px;
  color: var(--accent);
}

.item-card h3 {
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text);
}

.item-card p {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-tags,
.rag-item-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.item-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--panel-strong);
  border: 1px solid var(--border);
  color: var(--text-3);
}

.item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  font-size: 9.5px;
  color: var(--text-3);
}

.item-foot .mono {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confidence {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
}

.confidence i {
  display: block;
  height: 3px;
  border-radius: 2px;
  background: var(--success);
  max-width: 30px;
}

.item-version {
  position: absolute;
  top: 14px;
  right: 14px;
  font-size: 9px;
  color: var(--text-3);
  display: none;
}

.rag-panel {
  overflow: hidden;
}

.rag-hero {
  padding: 26px clamp(18px, 3vw, 40px);
  background: radial-gradient(ellipse at 20% 0%, var(--accent-soft), transparent 60%);
  border-bottom: 1px solid var(--border);
}

.rag-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.2em;
  color: var(--accent);
}

.rag-hero h2 {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  margin: 7px 0 6px;
}

.rag-hero p {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.7;
  max-width: 720px;
}

.rag-search {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  max-width: 720px;
}

.rag-search .search-box {
  flex: 1;
  width: auto;
}

.rag-search .input {
  min-height: 44px;
  font-size: 13.5px;
}

.rag-examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.rag-results {
  padding: 18px clamp(18px, 3vw, 40px) 24px;
}

.rag-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
  margin-bottom: 14px;
}

.rag-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rag-item {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-inset);
  transition: border-color 0.16s ease;
}

.rag-item:hover {
  border-color: var(--border-strong);
}

.rag-rank {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-3);
  line-height: 1;
  flex: none;
  padding-top: 2px;
}

.rag-item-body {
  min-width: 0;
  flex: 1;
}

.rag-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.rag-code {
  font-size: 10px;
  color: var(--accent);
}

.rag-score {
  margin-left: auto;
  font-size: 11px;
  color: var(--teal);
}

.rag-item h3 {
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text);
  margin-bottom: 4px;
}

.rag-item p {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
}

.rag-item-foot {
  margin-top: 8px;
  font-size: 9.5px;
  color: var(--text-3);
  align-items: center;
  gap: 10px;
}

.rag-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 46px 16px 52px;
  color: var(--text-3);
  font-size: 12px;
  text-align: center;
}

.rag-orbit {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 1px dashed var(--border-strong);
  color: var(--accent);
  background: var(--panel-inset);
}

.rule-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.rule-desc {
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-2);
  padding: 12px 14px;
  border-left: 2px solid var(--accent);
  background: var(--panel-inset);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.rule-section {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  margin: 16px 0 8px;
}

@media (max-width: 1279px) {
  .k-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .item-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .k-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .k-stat strong {
    font-size: 21px;
  }
  .rule-head {
    flex-direction: column;
    align-items: stretch;
  }
  .rule-head .toolbar {
    flex-wrap: wrap;
  }
  .category-select {
    flex: 1;
    width: auto;
  }
  .search-box {
    width: 100%;
  }
  .items-head {
    flex-direction: column;
    align-items: stretch;
  }
  .items-head .search-box {
    width: 100%;
    margin-left: 0;
  }
  .item-grid {
    grid-template-columns: 1fr;
    padding: 12px;
  }
  .rag-search {
    flex-direction: column;
  }
  .rag-hero {
    padding: 20px 16px;
  }
  .rag-results {
    padding: 14px 16px 20px;
  }
  .rag-rank {
    font-size: 16px;
  }
}
</style>
