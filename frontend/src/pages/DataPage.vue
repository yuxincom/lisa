<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dataApi, systemApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { AdapterOverview, CoverageResponse, DataSource, KitSourceFreshness, QualityResponse } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import RingGauge from '@/components/RingGauge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import Sparkline from '@/components/Sparkline.vue'

const ui = useUiStore()
const auth = useAuthStore()

const quality = ref<QualityResponse | null>(null)
const coverage = ref<CoverageResponse | null>(null)
const ingest = ref<AdapterOverview | null>(null)
const loading = ref(false)
const checking = ref(false)
const syncing = ref(false)
const error = ref('')
const dimensionIndex = ref(0)

const KIND_LABELS: Record<string, string> = {
  materials: 'ERP BOM 物料需求',
  stock: 'WMS 库存快照',
  inbound: '在途 / 采购承诺',
  tools: 'MES 工装与刀具',
  qualifications: 'HR 技能矩阵',
  inspections: 'QMS 检验结论',
}
const CHANNEL_LABELS: Record<string, string> = { file: '文件落地', http: 'HTTP 拉取', db: '中间库直连' }

const activeDimension = computed(() => quality.value?.dimensions[dimensionIndex.value] || null)
const gateTone = computed(() => (quality.value?.gate.passed ? 'var(--success)' : 'var(--danger)'))
const sources = computed<DataSource[]>(() => quality.value?.sources || [])

const freshnessRows = computed(() =>
  Object.entries(ingest.value?.freshness || {}).map(([kind, value]) => ({
    kind,
    label: KIND_LABELS[kind] || kind,
    ...(value as KitSourceFreshness),
  })),
)
const channels = computed(() => ingest.value?.sources || [])
const canManageIngest = computed(() => auth.isAdmin)

function freshnessTone(row: KitSourceFreshness) {
  if (!row.rows) return 'var(--text-3)'
  if (row.age_hours === null) return 'var(--text-3)'
  if (row.age_hours <= 4) return 'var(--success)'
  if (row.age_hours <= 24) return 'var(--warning)'
  return 'var(--danger)'
}

function ageLabel(row: KitSourceFreshness) {
  if (!row.rows) return '未接入'
  if (row.age_hours === null) return '—'
  if (row.age_hours < 1) return `${Math.round(row.age_hours * 60)} 分钟前`
  return `${row.age_hours.toFixed(1)} 小时前`
}

function scoreColor(score: number) {
  if (score >= 95) return 'var(--success)'
  if (score >= 90) return 'var(--teal)'
  if (score >= 80) return 'var(--warning)'
  return 'var(--danger)'
}

function sourceTone(status: string) {
  return status === 'online' ? 'success' : status === 'degraded' ? 'warning' : 'danger'
}

function datasetTone(status: string) {
  return status === 'complete' ? 'var(--success)' : status === 'in_progress' ? 'var(--accent)' : 'var(--blue)'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [q, c, ingestRes] = await Promise.all([dataApi.quality(), dataApi.coverage(), systemApi.adapters()])
    quality.value = q
    coverage.value = c
    ingest.value = ingestRes
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function runSync() {
  syncing.value = true
  try {
    const result = await systemApi.runAdapters(true)
    await load()
    const failed = result.ran.filter((item) => item.error).length
    if (!result.ran.length) {
      ui.info('没有到点的接入通道', '请先在配置清单里登记外部源，或用 CLI 导入 CSV 模板')
    } else if (failed) {
      ui.error(`${failed} 个通道同步失败`, result.ran.find((item) => item.error)?.error?.message || '')
    } else {
      ui.success('外部主数据同步完成', `${result.ran.length} 个通道 · ${result.ran.reduce((sum, item) => sum + (item.rows || 0), 0)} 行`)
    }
  } catch (err) {
    ui.error('同步失败', errorMessage(err))
  } finally {
    syncing.value = false
  }
}

async function runCheck() {
  checking.value = true
  try {
    quality.value = await dataApi.check()
    ui.success('L0 五维点检完成', `综合得分 ${quality.value.overall}% · ${quality.value.gate.label}`)
  } catch (err) {
    ui.error('点检失败', errorMessage(err))
  } finally {
    checking.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L0 · 数据治理基座"
      title="数据质量门禁"
      subtitle="完整性 · 及时性 · 一致性 · 准确性 · 唯一性，五维全部 ≥90% 方可进入排产链路"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button class="btn btn-primary" type="button" :disabled="checking" @click="runCheck">
          <span v-if="checking" class="spinner" />
          <AppIcon v-else name="activity" :size="15" />
          {{ checking ? '点检中…' : '运行五维点检' }}
        </button>
      </template>
      <template #meta>
        <span>采集时间 {{ formatDateTime(quality?.checked_at) }}</span>
        <span class="meta-dot" />
        <span>阈值 <strong class="text-accent">{{ quality?.threshold ?? 90 }}%</strong></span>
      </template>
    </PageHeader>

    <div v-if="error" class="empty">
      <AppIcon name="alert" :size="22" />
      {{ error }}
    </div>

    <div class="gate-hero panel" :class="{ passed: quality?.gate.passed }">
      <div class="gate-ring">
        <RingGauge
          :value="quality?.overall || 0"
          :size="150"
          :stroke="11"
          :color="gateTone"
          label="综合得分"
        />
      </div>
      <div class="gate-copy">
        <span class="gate-eyebrow">DATA QUALITY GATE</span>
        <div class="gate-title">
          <h2>{{ quality?.gate.label || 'L0 门禁状态读取中' }}</h2>
          <StatusBadge :label="quality?.gate.passed ? '通过' : '阻断'" :tone="quality?.gate.passed ? 'success' : 'danger'" />
        </div>
        <p class="gate-message">{{ quality?.gate.message || '正在校验五维数据质量…' }}</p>
        <div class="gate-meta">
          <div>
            <span>数据源</span>
            <strong class="num">{{ sources.length }}</strong>
          </div>
          <div>
            <span>在线</span>
            <strong class="num text-success">{{ sources.filter((s) => s.status === 'online').length }}</strong>
          </div>
          <div>
            <span>降级</span>
            <strong class="num text-warning">{{ sources.filter((s) => s.status === 'degraded').length }}</strong>
          </div>
          <div>
            <span>离线</span>
            <strong class="num text-danger">{{ sources.filter((s) => s.status === 'offline').length }}</strong>
          </div>
        </div>
      </div>
      <div class="gate-dim-list">
        <button
          v-for="(dim, index) in quality?.dimensions || []"
          :key="dim.key"
          type="button"
          class="gate-dim"
          :class="{ active: dimensionIndex === index }"
          @click="dimensionIndex = index"
        >
          <span class="gate-dim-name">{{ dim.label || dim.key }}</span>
          <span class="gate-dim-score num" :style="{ color: scoreColor(dim.score) }">{{ dim.score }}%</span>
          <span class="gate-dim-state" :class="dim.passed ? 'ok' : 'bad'">
            {{ dim.passed ? '达标' : '未达标' }}
          </span>
        </button>
      </div>
    </div>

    <div class="dimension-grid">
      <section
        v-for="(dim, index) in quality?.dimensions || []"
        :key="dim.key"
        class="panel dim-card"
        :class="{ active: dimensionIndex === index }"
        @mouseenter="dimensionIndex = index"
      >
        <div class="dim-head">
          <div>
            <span class="dim-index mono">D{{ index + 1 }}</span>
            <h3>{{ dim.label || dim.key }}</h3>
          </div>
          <StatusBadge :label="dim.passed ? '达标' : '未达标'" :tone="dim.passed ? 'success' : 'danger'" />
        </div>
        <p class="dim-desc">{{ dim.description }}</p>
        <div class="dim-score-row">
          <span class="dim-score num" :style="{ color: scoreColor(dim.score) }">{{ dim.score }}<small>%</small></span>
          <span class="dim-threshold">阈值 {{ dim.threshold }}%</span>
        </div>
        <div class="progress dim-progress">
          <i :style="{ width: `${Math.min(100, dim.score)}%`, background: scoreColor(dim.score) }" />
        </div>
        <div class="dim-trend">
          <Sparkline :values="dim.trend.map((point) => point.score)" :color="scoreColor(dim.score)" :height="30" />
        </div>
        <div class="dim-foot">
          <span class="badge badge-muted">{{ dim.source }}</span>
          <span class="muted">{{ formatDateTime(dim.checked_at) }}</span>
        </div>
      </section>
    </div>

    <div class="data-grid">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />数据源接入</div>
          <span class="panel-sub">{{ sources.length }} 个系统 · 111 个接口</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>系统</th>
                <th>类型</th>
                <th>状态</th>
                <th>时延</th>
                <th>记录数</th>
                <th>质量</th>
                <th>负责部门</th>
                <th>最近同步</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="source in sources" :key="source.id">
                <td>
                  <div class="source-cell">
                    <span class="source-code mono">{{ source.code }}</span>
                    <span class="cell-strong">{{ source.name }}</span>
                  </div>
                </td>
                <td>{{ source.type }}</td>
                <td>
                  <StatusBadge :label="source.status === 'online' ? '在线' : source.status === 'degraded' ? '降级' : '离线'" :tone="sourceTone(source.status)" />
                </td>
                <td class="num">{{ formatNumber(source.latency_ms) }} ms</td>
                <td class="num">{{ formatNumber(source.records) }}</td>
                <td>
                  <span class="source-quality num" :style="{ color: scoreColor(source.quality) }">{{ source.quality }}%</span>
                </td>
                <td>{{ source.owner }}</td>
                <td class="muted">{{ formatDateTime(source.last_sync) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />四区间数据覆盖</div>
          <span class="panel-sub">一期验收口径</span>
        </div>
        <div class="panel-body coverage-body">
          <div v-for="dataset in coverage?.datasets || []" :key="dataset.code" class="dataset">
            <div class="dataset-head">
              <div>
                <span class="dataset-code mono">{{ dataset.code }}</span>
                <strong>{{ dataset.name }}</strong>
              </div>
              <span class="dataset-count num">
                {{ formatNumber(dataset.current) }}<small> / {{ formatNumber(dataset.target) }} {{ dataset.unit }}</small>
              </span>
            </div>
            <div class="progress">
              <i :style="{ width: `${Math.min(100, (dataset.current / dataset.target) * 100)}%`, background: datasetTone(dataset.status) }" />
            </div>
            <span class="dataset-note">{{ dataset.note }}</span>
          </div>

          <div class="phase-track">
            <div v-for="phase in coverage?.phases || []" :key="phase.name" class="phase">
              <div class="phase-dot" :class="{ done: phase.complete }">
                <AppIcon v-if="phase.complete" name="check" :size="11" />
              </div>
              <div class="phase-copy">
                <strong>{{ phase.name }}</strong>
                <span>{{ formatNumber(phase.count) }} 条 · 准确率 {{ phase.accuracy }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <section class="panel ingest-panel">
      <div class="panel-head">
        <div class="panel-title"><span class="title-mark" />外部主数据接入（齐套九要素的供给侧）</div>
        <button v-if="canManageIngest" class="btn btn-primary" type="button" :disabled="syncing" @click="runSync">
          <span v-if="syncing" class="spinner" />
          <AppIcon v-else name="refresh" :size="14" />
          {{ syncing ? '同步中…' : '立即同步' }}
        </button>
      </div>
      <div class="ingest-grid">
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>数据种类</th>
                <th>源系统</th>
                <th>行数</th>
                <th>最近写入</th>
                <th>时效</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in freshnessRows" :key="row.kind">
                <td>
                  <div class="source-cell">
                    <span class="source-code mono">{{ row.kind }}</span>
                    <span class="cell-strong">{{ row.label }}</span>
                  </div>
                </td>
                <td>{{ row.rows ? formatDateTime(row.as_of) : '待接入' }}</td>
                <td class="num">{{ formatNumber(row.rows) }}</td>
                <td class="muted">{{ ageLabel(row) }}</td>
                <td>
                  <span class="freshness-dot" :style="{ background: freshnessTone(row) }" />
                  <span :style="{ color: freshnessTone(row) }">{{ row.rows ? (row.age_hours !== null && row.age_hours > 24 ? '过期' : '新鲜') : '未接入' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="ingest-channels">
          <div v-if="!channels.length" class="channel-empty">
            <AppIcon name="info" :size="14" />
            <p>
              还没有登记自动接入通道。三种方式任选：<strong>文件落地</strong>（源系统按 CSV 模板定时导出到共享目录）、
              <strong>HTTP 拉取</strong>（内网 https 接口）、<strong>中间库直连</strong>（只读 SELECT 视图）。
              配置口径见 <code>docs/投产配置清单.md</code> 的 D 组，模板在 <code>deploy/templates/</code>。
            </p>
            <p class="muted">也可以先手工导入：<code>python -m app.management kit-data stock ../deploy/templates/齐套-库存.csv</code></p>
          </div>
          <div v-for="channel in channels" :key="channel.name" class="channel" :class="{ failed: !!channel.error }">
            <div class="channel-head">
              <strong>{{ channel.name }}</strong>
              <StatusBadge
                :label="channel.error ? '异常' : channel.enabled ? '启用' : '停用'"
                :tone="channel.error ? 'danger' : channel.enabled ? 'success' : 'muted'"
              />
            </div>
            <div class="channel-meta">
              <span>{{ CHANNEL_LABELS[channel.channel] || channel.channel }}</span>
              <span>写入 {{ channel.kind }}</span>
              <span>每 {{ channel.interval_minutes }} 分钟</span>
              <span v-if="channel.rows !== null">{{ channel.rows }} 行</span>
            </div>
            <div class="channel-time">
              <span v-if="channel.last_sync">上次 {{ formatDateTime(channel.last_sync) }}</span>
              <span v-if="channel.next_sync">下次 {{ formatDateTime(channel.next_sync) }}</span>
            </div>
            <p v-if="channel.error" class="channel-error">{{ channel.error.code }} · {{ channel.error.message }}</p>
          </div>
        </div>
      </div>
    </section>

    <div class="meta-grid">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />主数据规模</div>
        </div>
        <div class="panel-body meta-cards">
          <div class="meta-card"><span>接口</span><strong class="num">{{ coverage?.interface_count ?? '—' }}</strong></div>
          <div class="meta-card"><span>映射关系</span><strong class="num">{{ coverage?.mapping_count ?? '—' }}</strong></div>
          <div class="meta-card"><span>产品</span><strong class="num">{{ coverage?.product_count ?? '—' }}</strong></div>
          <div class="meta-card"><span>工序</span><strong class="num">{{ coverage?.operation_count ?? '—' }}</strong></div>
          <div class="meta-card"><span>资源</span><strong class="num">{{ coverage?.resources ?? '—' }}</strong></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />标注工程</div>
          <span class="panel-sub">专家一致性校验</span>
        </div>
        <div class="panel-body annotation">
          <div class="annotation-row">
            <span>标注模板</span>
            <strong class="num">{{ coverage?.annotation.templates ?? '—' }}</strong>
          </div>
          <div class="annotation-row">
            <span>字段定义</span>
            <strong class="num">{{ coverage?.annotation.fields ?? '—' }}</strong>
          </div>
          <div class="annotation-row">
            <span>最小标注集</span>
            <strong class="num">{{ coverage?.annotation.minimum_set ?? '—' }}</strong>
          </div>
          <div class="annotation-row">
            <span>专家确认率</span>
            <strong class="num text-success">{{ coverage?.annotation.expert_confirm_rate ?? '—' }}%</strong>
          </div>
          <div class="annotation-row">
            <span>一致性 Kappa</span>
            <strong class="num text-accent">{{ coverage?.annotation.kappa ?? '—' }}</strong>
          </div>
        </div>
      </section>
    </div>

    <div v-if="activeDimension" class="panel detail-strip">
      <div class="detail-strip-copy">
        <span class="badge badge-teal">{{ activeDimension.source }}</span>
        <strong>{{ activeDimension.label || activeDimension.key }}</strong>
        <span class="muted">{{ activeDimension.description }}</span>
      </div>
      <div class="detail-strip-stats">
        <span>最近点检 <strong>{{ formatDateTime(activeDimension.checked_at) }}</strong></span>
        <span v-if="activeDimension.detail" class="detail-sample">
          {{ activeDimension.detail.sample || '样本数据正常' }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}

.gate-hero {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(280px, 0.9fr);
  gap: 24px;
  align-items: center;
  padding: 22px 24px;
  margin-bottom: 16px;
  border-color: color-mix(in srgb, var(--accent) 18%, var(--border));
}

.gate-hero.passed {
  border-color: color-mix(in srgb, var(--success) 24%, var(--border));
}

.gate-ring {
  flex: none;
}

.gate-eyebrow {
  font-size: 10px;
  letter-spacing: 0.2em;
  font-weight: 700;
  color: var(--accent);
}

.gate-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 6px;
}

.gate-title h2 {
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 700;
}

.gate-message {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.7;
  max-width: 520px;
}

.gate-meta {
  display: flex;
  gap: 22px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.gate-meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.gate-meta span {
  font-size: 10.5px;
  color: var(--text-3);
}

.gate-meta strong {
  font-size: 17px;
  color: var(--text);
}

.gate-dim-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-left: 1px solid var(--border);
  padding-left: 18px;
}

.gate-dim {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  text-align: left;
  transition: all 0.16s ease;
}

.gate-dim:hover,
.gate-dim.active {
  background: var(--panel-inset);
  border-color: var(--border);
}

.gate-dim-name {
  font-size: 12px;
}

.gate-dim-score {
  font-size: 13px;
  font-weight: 700;
}

.gate-dim-state {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}

.gate-dim-state.ok {
  color: var(--success);
  background: var(--success-soft);
}

.gate-dim-state.bad {
  color: var(--danger);
  background: var(--danger-soft);
}

.dimension-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.dim-card {
  padding: 15px 16px;
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.dim-card:hover,
.dim-card.active {
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.dim-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.dim-index {
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.1em;
}

.dim-head h3 {
  font-size: 13.5px;
  font-weight: 650;
  margin-top: 2px;
}

.dim-desc {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
  margin: 8px 0 12px;
  min-height: 36px;
}

.dim-score-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.dim-score {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
}

.dim-score small {
  font-size: 12px;
  color: var(--text-3);
}

.dim-threshold {
  font-size: 10.5px;
  color: var(--text-3);
}

.dim-progress {
  margin: 9px 0 4px;
  height: 5px;
}

.dim-trend {
  margin: 2px -2px 0;
}

.dim-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 6px;
  font-size: 9.5px;
}

.data-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.source-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.source-code {
  font-size: 10px;
  color: var(--accent);
}

.source-quality {
  font-weight: 700;
}

.coverage-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dataset-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.dataset-head > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.dataset-code {
  font-size: 10px;
  color: var(--accent);
}

.dataset-head strong {
  font-size: 12.5px;
  color: var(--text);
}

.dataset-count {
  font-size: 11.5px;
  color: var(--text-2);
  white-space: nowrap;
}

.dataset-count small {
  color: var(--text-3);
  font-size: 10px;
}

.dataset-note {
  display: block;
  font-size: 10.5px;
  color: var(--text-3);
  margin-top: 5px;
}

.phase-track {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
  margin-top: 2px;
}

.phase {
  display: flex;
  gap: 10px;
  position: relative;
  padding-bottom: 12px;
}

.phase:last-child {
  padding-bottom: 0;
}

.phase:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 16px;
  bottom: 0;
  width: 1px;
  background: var(--border);
}

.phase-dot {
  width: 15px;
  height: 15px;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  display: grid;
  place-items: center;
  flex: none;
  color: var(--success);
  background: var(--panel-solid);
  margin-top: 1px;
}

.phase-dot.done {
  border-color: var(--success);
  background: var(--success-soft);
}

.phase-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.phase-copy strong {
  font-size: 12px;
  color: var(--text);
}

.phase-copy span {
  font-size: 10.5px;
  color: var(--text-3);
}

.meta-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.meta-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.meta-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.meta-card span {
  font-size: 10.5px;
  color: var(--text-3);
}

.meta-card strong {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--text);
}

.annotation {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.annotation-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-3);
}

.annotation-row:last-child {
  border-bottom: 0;
}

.annotation-row strong {
  color: var(--text);
  font-size: 13px;
}

.detail-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 18px;
  flex-wrap: wrap;
}

.detail-strip-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.detail-strip-copy strong {
  color: var(--text);
}

.detail-strip-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: var(--text-3);
  flex-wrap: wrap;
}

.detail-strip-stats strong {
  color: var(--text-2);
}

.detail-sample {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--mono);
}

.ingest-panel {
  margin-bottom: 16px;
}

.ingest-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  gap: 16px;
  padding: 16px 18px 18px;
}

.ingest-channels {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-left: 1px solid var(--border);
  padding-left: 16px;
}

.channel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.channel.failed {
  border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
}

.channel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.channel-head strong {
  font-size: 12.5px;
  color: var(--text);
}

.channel-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  font-size: 11px;
  color: var(--text-3);
}

.channel-time {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 10.5px;
  color: var(--text-3);
}

.channel-error {
  margin: 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--danger-soft);
  color: var(--danger);
  font-family: var(--mono);
  font-size: 10.5px;
  line-height: 1.5;
  word-break: break-all;
}

.channel-empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-2);
}

.channel-empty svg {
  color: var(--text-3);
}

.channel-empty strong {
  color: var(--text);
}

.channel-empty code {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-2);
}

.freshness-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
  border-radius: 50%;
  vertical-align: 1px;
}

@media (max-width: 1439px) {
  .dimension-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .gate-hero {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .gate-dim-list {
    grid-column: 1 / -1;
    flex-direction: row;
    border-left: 0;
    padding-left: 0;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    flex-wrap: wrap;
  }
  .gate-dim {
    flex: 1;
    min-width: 150px;
  }
}

@media (max-width: 1023px) {
  .dimension-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .data-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }
  .ingest-grid {
    grid-template-columns: 1fr;
  }
  .ingest-channels {
    border-left: 0;
    padding-left: 0;
    border-top: 1px solid var(--border);
    padding-top: 14px;
  }
  .meta-cards {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .gate-hero {
    grid-template-columns: 1fr;
    padding: 16px;
    text-align: left;
  }
  .gate-ring {
    justify-self: center;
  }
  .dimension-grid {
    grid-template-columns: 1fr;
  }
  .meta-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .gate-dim {
    min-width: 0;
    width: 100%;
  }
  .gate-meta {
    gap: 16px;
  }
  .detail-strip {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
