<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { kitsApi, ordersApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { KitCheck, KitOverview, Order } from '@/types'
import { formatDateTime, statusTone } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import RingGauge from '@/components/RingGauge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'
import BaseModal from '@/components/BaseModal.vue'

const CHECKPOINTS = [
  { key: 'pre_schedule', label: '排产前', desc: '订单进入排产池之前的齐套准入' },
  { key: 'post_schedule', label: '排产后', desc: '排产结果冻结前校验九要素' },
  { key: 'pre_start', label: '开工前', desc: '开工前最后一道硬阻断校验' },
]

const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const overview = ref<KitOverview | null>(null)
const checks = ref<KitCheck[]>([])
const counts = ref<Record<string, number>>({})
const checkpoint = ref('post_schedule')
const statusFilter = ref('')
const search = ref('')
const loading = ref(false)
const error = ref('')

const detail = ref<KitCheck | null>(null)
const detailOpen = ref(false)
const orderSummary = ref<{ order_no: string; product_name: string; priority?: string; kit_status?: string } | null>(null)
const checkpointHistory = ref<KitCheck[]>([])
const detailLoading = ref(false)

const checkOpen = ref(false)
const orderOptions = ref<Order[]>([])
const chosenOrder = ref<number | null>(null)
const chosenCheckpoint = ref('pre_start')
const checking = ref(false)

let searchTimer: number | undefined

const canCheck = computed(() => auth.can('kits:read'))
const activeCheckpoint = computed(() => CHECKPOINTS.find((item) => item.key === checkpoint.value) || CHECKPOINTS[1])
const totalChecks = computed(() => overview.value?.by_checkpoint.reduce((sum, row) => sum + row.total, 0) || 0)
const totalMissing = computed(() =>
  overview.value?.by_checkpoint.reduce((sum, row) => sum + row.missing + row.blocked, 0) || 0,
)
const postRate = computed(() => overview.value?.post_schedule_rate || 0)
const hiddenOrders = computed(() => overview.value?.hidden_orders_by_clearance ?? 0)
const timerTone = computed(() => (postRate.value >= 85 ? 'var(--success)' : postRate.value >= 60 ? 'var(--warning)' : 'var(--danger)'))

const drawerNote = computed(() => {
  const check = detail.value
  if (!check) return ''
  const unknown = check.elements.filter((element) => element.status === 'unknown')
  if (check.gaps.length) {
    return '存在缺口，需按责任归口在时效内闭环，开工前关键缺口将硬阻断。'
  }
  if (unknown.length) {
    return `${unknown.length} 项要素的外部源尚未接入（${unknown.map((element) => element.name).join('、')}），已按可判定要素计分，不宣布齐套。`
  }
  return '九要素全部实算通过，可进入排产与开工流程。'
})

const statusChips = computed(() => {
  const list = [
    { key: '', label: '全部', count: checks.value.length },
    { key: '齐套', label: '齐套', count: counts.value['齐套'] || 0 },
    { key: '缺项', label: '缺项', count: counts.value['缺项'] || 0 },
    { key: '阻断', label: '阻断', count: counts.value['阻断'] || 0 },
    { key: '待接入', label: '待接入', count: counts.value['待接入'] || 0 },
  ]
  return list
})

async function loadOverview() {
  try {
    overview.value = await kitsApi.overview()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadChecks() {
  loading.value = true
  error.value = ''
  try {
    const res = await kitsApi.list({
      checkpoint: checkpoint.value,
      status: statusFilter.value || undefined,
      search: search.value.trim() || undefined,
      limit: 100,
    })
    checks.value = res.items
    counts.value = res.counts || {}
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function setCheckpoint(key: string) {
  checkpoint.value = key
  loadChecks()
}

function onSearch() {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(loadChecks, 280)
}

function setStatus(key: string) {
  statusFilter.value = key
  loadChecks()
}

function scoreColor(score: number) {
  if (score >= 90) return 'var(--success)'
  if (score >= 70) return 'var(--warning)'
  return 'var(--danger)'
}

function elementTone(status: string) {
  if (status === 'ok') return 'success'
  if (status === 'unknown') return 'muted'
  return 'danger'
}

function elementLabel(status: string) {
  if (status === 'ok') return '齐套'
  if (status === 'unknown') return '未接入'
  return '缺项'
}

function elementIcon(status: string) {
  if (status === 'ok') return 'check'
  if (status === 'unknown') return 'info'
  return 'alert'
}

async function openDetail(check: KitCheck) {
  detail.value = check
  detailOpen.value = true
  detailLoading.value = true
  orderSummary.value = null
  checkpointHistory.value = []
  try {
    const res = await kitsApi.detail(check.order_id)
    orderSummary.value = res.order
    checkpointHistory.value = res.checkpoints
  } catch (err) {
    ui.error('加载齐套详情失败', errorMessage(err))
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  detail.value = null
}

async function openCheck() {
  checkOpen.value = true
  chosenOrder.value = null
  chosenCheckpoint.value = checkpoint.value
  if (!orderOptions.value.length) {
    try {
      const res = await ordersApi.list({ limit: 200 })
      orderOptions.value = res.items
    } catch (err) {
      ui.error('订单列表加载失败', errorMessage(err))
    }
  }
}

async function runCheck() {
  if (!chosenOrder.value) {
    ui.warning('请选择订单')
    return
  }
  checking.value = true
  try {
    const result = await kitsApi.check(chosenOrder.value, chosenCheckpoint.value)
    ui.success('齐套检查完成', `${result.order_no} · ${result.checkpoint_label} · ${result.status}`)
    checkOpen.value = false
    await Promise.all([loadOverview(), loadChecks()])
    openDetail(result)
  } catch (err) {
    ui.error('齐套检查失败', errorMessage(err))
  } finally {
    checking.value = false
  }
}

function gotoTicket() {
  if (detail.value) router.push({ name: 'orders', query: { order: detail.value.order_id } })
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadChecks()])
})

onBeforeUnmount(() => window.clearTimeout(searchTimer))
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="M-03 · 齐套智能体"
      title="齐套校验台"
      subtitle="九要素快照校验 · 开工前关键缺口硬阻断 · 齐套率由 60% 向 100% 演进"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="loadChecks">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button v-if="canCheck" class="btn btn-primary" type="button" @click="openCheck">
          <AppIcon name="play" :size="15" />
          执行齐套检查
        </button>
      </template>
      <template #meta>
        <span>更新时间 {{ formatDateTime(overview?.updated_at) }}</span>
        <span class="meta-dot" />
        <span>排产后齐套率 <strong class="text-accent">{{ postRate }}%</strong></span>
        <template v-if="hiddenOrders > 0">
          <span class="meta-dot" />
          <span class="meta-hidden">{{ hiddenOrders }} 张订单因密级未计入</span>
        </template>
      </template>
    </PageHeader>

    <div v-if="hiddenOrders > 0" class="clearance-note">
      <AppIcon name="lock" :size="14" />
      <span>
        齐套率只统计你密级可见的 <strong class="num">{{ totalChecks }}</strong> 单；另有
        <strong class="num">{{ hiddenOrders }}</strong> 张订单高于你的可读范围，它们的缺口不会出现在这里，也不参与齐套率——
        这不是「没有缺口」，是「看不见」。
      </span>
    </div>

    <div class="kit-hero">
      <section class="panel rate-panel">
        <div class="panel-body rate-body">
          <RingGauge :value="postRate" :size="132" :stroke="10" :color="timerTone" label="排产后齐套率" />
          <div class="rate-copy">
            <span class="rate-eyebrow">KIT READY RATE</span>
            <h2>齐套决定开工节奏</h2>
            <p>M-03 在排产前、排产后、开工前三道时点校验工装、主辅材、刀具、工艺路线、资质、WIP、设备与能力九要素；开工前关键缺口直接硬阻断。</p>
            <div class="rate-tags">
              <span class="badge badge-teal"><span class="dot" />当前时点 {{ activeCheckpoint.label }}</span>
              <span class="badge badge-muted">校验 {{ totalChecks }} 单次</span>
              <span class="badge badge-danger">缺口 / 阻断 {{ totalMissing }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />缺口责任归口</div>
          <span class="panel-sub">Top owners</span>
        </div>
        <div class="panel-body owners-body">
          <div v-if="!overview?.gap_owners.length" class="empty compact">暂无缺口</div>
          <div v-for="owner in overview?.gap_owners.slice(0, 6) || []" :key="owner.owner" class="owner-row">
            <div class="owner-head">
              <span>{{ owner.owner }}</span>
              <strong class="num">{{ owner.count }}</strong>
            </div>
            <div class="progress"><i :style="{ width: `${Math.min(100, owner.count * 12 + 12)}%` }" /></div>
          </div>
        </div>
      </section>
    </div>

    <div class="checkpoint-grid">
      <button
        v-for="item in CHECKPOINTS"
        :key="item.key"
        type="button"
        class="checkpoint-card panel"
        :class="{ active: checkpoint === item.key }"
        @click="setCheckpoint(item.key)"
      >
        <div class="checkpoint-top">
          <span class="checkpoint-label">{{ item.label }}</span>
          <span class="checkpoint-rate num" :class="{ accent: checkpoint === item.key }">
            {{ overview?.by_checkpoint.find((row) => row.checkpoint === item.key)?.rate ?? 0 }}<small>%</small>
          </span>
        </div>
        <p class="checkpoint-desc">{{ item.desc }}</p>
        <div class="checkpoint-stats">
          <span>校验 <strong class="num">{{ overview?.by_checkpoint.find((row) => row.checkpoint === item.key)?.total ?? 0 }}</strong></span>
          <span>缺项 <strong class="num text-warning">{{ overview?.by_checkpoint.find((row) => row.checkpoint === item.key)?.missing ?? 0 }}</strong></span>
          <span>阻断 <strong class="num text-danger">{{ overview?.by_checkpoint.find((row) => row.checkpoint === item.key)?.blocked ?? 0 }}</strong></span>
        </div>
        <div class="progress thin">
          <i :style="{ width: `${overview?.by_checkpoint.find((row) => row.checkpoint === item.key)?.rate ?? 0}%` }" />
        </div>
      </button>
    </div>

    <section class="panel list-panel">
      <div class="panel-head list-head">
        <div class="panel-title">
          <span class="title-mark" />
          {{ activeCheckpoint.label }}校验清单
          <span class="panel-sub">{{ checks.length }} 条</span>
        </div>
        <div class="toolbar">
          <div class="search-box">
            <AppIcon name="search" :size="14" />
            <input v-model="search" class="input" placeholder="订单号 / 产品" @input="onSearch" />
          </div>
          <div class="segmented status-seg">
            <button
              v-for="chip in statusChips"
              :key="chip.key"
              type="button"
              :class="{ active: statusFilter === chip.key }"
              @click="setStatus(chip.key)"
            >
              {{ chip.label }} <span class="seg-count">{{ chip.count }}</span>
            </button>
          </div>
        </div>
      </div>

      <div v-if="error" class="empty">
        <AppIcon name="alert" :size="22" />
        {{ error }}
      </div>
      <div v-else-if="loading" class="kit-loading">
        <span class="spinner" /> 正在读取齐套快照…
      </div>
      <div v-else-if="!checks.length" class="empty">
        <div class="empty-icon"><AppIcon name="check" :size="20" /></div>
        当前时点暂无齐套记录，可执行一次齐套检查
      </div>
      <div v-else class="kit-rows">
        <button
          v-for="check in checks"
          :key="check.id"
          type="button"
          class="kit-row"
          @click="openDetail(check)"
        >
          <div class="kit-main">
            <span class="kit-order mono">{{ check.order_no }}</span>
            <div class="kit-product">
              <strong>{{ check.product_name }}</strong>
              <span class="kit-sub">缺口 {{ check.gaps.length }} 项 · {{ formatDateTime(check.checked_at) }}</span>
            </div>
          </div>
          <div class="kit-score">
            <div class="score-bar">
              <span>齐套度</span>
              <strong class="num" :style="{ color: scoreColor(check.score) }">{{ check.score }}%</strong>
            </div>
            <div class="progress thin">
              <i :style="{ width: `${check.score}%`, background: scoreColor(check.score) }" />
            </div>
          </div>
          <div class="kit-gaps hide-mobile">
            <span
              v-for="gap in check.gaps.slice(0, 3)"
              :key="gap.key"
              class="gap-chip"
              :class="{ critical: gap.critical }"
            >
              {{ gap.name }}
            </span>
            <span v-if="!check.gaps.length" class="muted">九要素齐全</span>
            <span v-if="check.gaps.length > 3" class="muted">+{{ check.gaps.length - 3 }}</span>
          </div>
          <StatusBadge :status="check.status" />
          <AppIcon name="chevron-right" :size="15" class="row-arrow" />
        </button>
      </div>
    </section>

    <BaseDrawer
      :model-value="detailOpen"
      width="620px"
      :title="detail ? `${detail.order_no} · ${detail.checkpoint_label}` : '齐套详情'"
      :subtitle="detail?.product_name"
      @update:model-value="closeDetail"
    >
      <template v-if="detail">
        <div class="drawer-hero">
          <RingGauge :value="detail.score" :size="108" :stroke="9" :color="scoreColor(detail.score)" label="齐套度" />
          <div class="drawer-hero-copy">
            <div class="drawer-badges">
              <StatusBadge :status="detail.status" />
              <span class="badge badge-muted">{{ detail.checkpoint_label }}</span>
              <span v-if="detail.gaps.some((gap) => gap.critical)" class="badge badge-danger">关键缺口</span>
            </div>
            <p class="drawer-note">{{ drawerNote }}</p>
            <div class="kv compact-kv">
              <span class="k">订单号</span>
              <span class="v mono">{{ detail.order_no }}</span>
            </div>
            <div class="kv compact-kv">
              <span class="k">检查时间</span>
              <span class="v">{{ formatDateTime(detail.checked_at) }}</span>
            </div>
          </div>
        </div>

        <h4 class="drawer-section-title">九要素快照</h4>
        <div class="element-grid">
          <div v-for="element in detail.elements" :key="element.key" class="element-card">
            <span class="element-icon" :class="elementTone(element.status)">
              <AppIcon :name="elementIcon(element.status)" :size="14" />
            </span>
            <div class="element-copy">
              <strong>{{ element.name }}</strong>
              <span class="element-source">{{ element.source }} · {{ element.value }}</span>
            </div>
            <span class="element-state" :class="elementTone(element.status)">
              {{ elementLabel(element.status) }}
            </span>
          </div>
        </div>

        <template v-if="detail.gaps.length">
          <h4 class="drawer-section-title">缺口与责任闭环</h4>
          <div class="gap-list">
            <div v-for="gap in detail.gaps" :key="gap.key" class="gap-card" :class="{ critical: gap.critical }">
              <div class="gap-head">
                <strong>{{ gap.name }}</strong>
                <span class="badge" :class="gap.critical ? 'badge-danger' : 'badge-warning'">
                  {{ gap.critical ? '关键' : '一般' }}
                </span>
              </div>
              <p class="gap-reason">{{ gap.reason }}</p>
              <div class="gap-meta">
                <span>归口 · {{ gap.owner }}</span>
                <span>时限 · {{ gap.due_hours }}h</span>
              </div>
              <div class="gap-action">
                <AppIcon name="arrow-right" :size="13" />
                {{ gap.action }}
              </div>
            </div>
          </div>
        </template>

        <h4 class="drawer-section-title">时点历史</h4>
        <div v-if="detailLoading" class="kit-loading"><span class="spinner" /> 加载中…</div>
        <div v-else-if="checkpointHistory.length" class="history-list">
          <div
            v-for="item in checkpointHistory"
            :key="item.id"
            class="history-row"
            :class="{ current: item.id === detail.id }"
          >
            <div class="history-dot" :class="statusTone(item.status)">
              <span />
            </div>
            <div class="history-copy">
              <strong>{{ item.checkpoint_label }}</strong>
              <span>{{ formatDateTime(item.checked_at) }}</span>
            </div>
            <span class="num">{{ item.score }}%</span>
            <StatusBadge :status="item.status" :dot="false" />
          </div>
        </div>
        <div v-else-if="!detailLoading" class="empty compact">暂无更多时点记录</div>
      </template>

      <template #footer>
        <button class="btn btn-ghost" type="button" @click="gotoTicket">
          <AppIcon name="orders" :size="14" />
          查看订单
        </button>
        <button
          v-if="canCheck && detail"
          class="btn btn-primary"
          type="button"
          @click="openCheck"
        >
          <AppIcon name="reset" :size="14" />
          重新检查
        </button>
      </template>
    </BaseDrawer>

    <BaseModal
      v-model="checkOpen"
      title="执行齐套检查"
      subtitle="选择订单与检查时点，M-03 将立即生成九要素快照并归档"
      width="520px"
    >
      <div class="form-stack">
        <label class="field">
          <span class="field-label">订单</span>
          <select v-model="chosenOrder" class="select">
            <option :value="null" disabled>选择订单</option>
            <option v-for="order in orderOptions" :key="order.id" :value="order.id">
              {{ order.order_no }} · {{ order.product_name }}（{{ order.priority }}）
            </option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">检查时点</span>
          <select v-model="chosenCheckpoint" class="select">
            <option v-for="item in CHECKPOINTS" :key="item.key" :value="item.key">
              {{ item.label }} · {{ item.desc }}
            </option>
          </select>
        </label>
        <p class="form-hint">
          <AppIcon name="shield" :size="13" />
          开工前时点若存在关键缺口，结果将标记为「阻断」并禁止写入 APS。
        </p>
      </div>
      <template #footer>
        <button class="btn btn-ghost" type="button" @click="checkOpen = false">取消</button>
        <button class="btn btn-primary" type="button" :disabled="checking || !chosenOrder" @click="runCheck">
          <span v-if="checking" class="spinner" />
          <AppIcon v-else name="play" :size="14" />
          {{ checking ? '校验中…' : '开始检查' }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}

.kit-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.rate-body {
  display: flex;
  align-items: center;
  gap: clamp(16px, 2.6vw, 34px);
  padding: 24px;
}

.rate-copy h2 {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  margin: 6px 0 8px;
}

.rate-copy p {
  font-size: 12.8px;
  color: var(--text-2);
  line-height: 1.75;
  max-width: 560px;
}

.rate-eyebrow {
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--accent);
  font-weight: 700;
}

.rate-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.owners-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
}

.owner-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 6px;
}

.owner-head strong {
  color: var(--text);
}

.progress.thin {
  height: 5px;
}

.progress.thin i {
  background: linear-gradient(90deg, var(--accent), var(--teal));
}

.checkpoint-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.checkpoint-card {
  text-align: left;
  padding: 16px 18px;
  color: var(--text);
  transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}

.checkpoint-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
}

.checkpoint-card.active {
  border-color: var(--accent-line);
  box-shadow: 0 0 0 1px var(--accent-line), 0 14px 34px rgba(0, 0, 0, 0.22);
}

.checkpoint-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.checkpoint-label {
  font-size: 14px;
  font-weight: 650;
}

.checkpoint-rate {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
}

.checkpoint-rate small {
  font-size: 12px;
  color: var(--text-3);
}

.checkpoint-rate.accent {
  color: var(--accent);
}

.checkpoint-desc {
  margin: 6px 0 12px;
  font-size: 11.8px;
  color: var(--text-3);
  line-height: 1.6;
  min-height: 34px;
}

.checkpoint-stats {
  display: flex;
  gap: 14px;
  font-size: 11.5px;
  color: var(--text-3);
  margin-bottom: 10px;
}

.checkpoint-stats strong {
  color: var(--text-2);
  font-weight: 600;
}

.list-head {
  flex-wrap: wrap;
}

.list-head .toolbar {
  flex: 1;
  justify-content: flex-end;
}

.search-box {
  width: 220px;
}

.seg-count {
  margin-left: 4px;
  font-size: 10.5px;
  opacity: 0.7;
}

.kit-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.kit-rows {
  display: flex;
  flex-direction: column;
}

.kit-row {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1.3fr) auto 18px;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  text-align: left;
  transition: background-color 0.16s ease;
}

.kit-row:last-child {
  border-bottom: 0;
}

.kit-row:hover {
  background: color-mix(in srgb, var(--panel-strong) 62%, transparent);
}

.kit-main {
  min-width: 0;
}

.kit-order {
  display: inline-block;
  font-size: 11.5px;
  color: var(--accent);
  margin-bottom: 5px;
}

.kit-product {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.kit-product strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kit-sub {
  font-size: 11px;
  color: var(--text-3);
}

.score-bar {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 6px;
}

.score-bar strong {
  font-size: 13px;
}

.kit-gaps {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
  font-size: 11px;
}

.gap-chip {
  padding: 2px 7px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-2);
  white-space: nowrap;
}

.gap-chip.critical {
  border-color: color-mix(in srgb, var(--danger) 34%, transparent);
  color: var(--danger);
  background: var(--danger-soft);
}

.row-arrow {
  color: var(--text-3);
}

.drawer-hero {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-inset);
  margin-bottom: 18px;
}

.drawer-hero-copy {
  flex: 1;
  min-width: 0;
}

.drawer-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.drawer-note {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.65;
  margin-bottom: 6px;
}

.compact-kv {
  padding: 5px 0;
  border-bottom: 0;
  font-size: 12px;
}

.drawer-section-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-3);
  text-transform: uppercase;
  margin: 20px 0 10px;
}

.drawer-section-title:first-of-type {
  margin-top: 0;
}

.element-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.element-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  min-width: 0;
}

.element-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  flex: none;
}

.element-icon.success {
  color: var(--success);
  background: var(--success-soft);
}

.element-icon.danger {
  color: var(--danger);
  background: var(--danger-soft);
}

.element-icon.muted {
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px dashed var(--border-2);
}

.element-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.element-copy strong {
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.element-source {
  font-size: 10px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.element-state {
  font-size: 10.5px;
  font-weight: 600;
  flex: none;
}

.element-state.success {
  color: var(--success);
}

.element-state.danger {
  color: var(--danger);
}

.element-state.muted {
  color: var(--text-3);
}

.gap-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gap-card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.gap-card.critical {
  border-color: color-mix(in srgb, var(--danger) 26%, transparent);
}

.gap-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 5px;
}

.gap-head strong {
  font-size: 12.5px;
  color: var(--text);
}

.gap-reason {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.6;
}

.gap-meta {
  display: flex;
  gap: 14px;
  font-size: 11px;
  color: var(--text-3);
  margin-top: 6px;
}

.gap-action {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  font-size: 11.5px;
  color: var(--teal);
}

.history-list {
  display: flex;
  flex-direction: column;
}

.history-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-2);
}

.history-row:last-child {
  border-bottom: 0;
}

.history-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid currentColor;
  flex: none;
  display: grid;
  place-items: center;
}

.history-dot.success {
  color: var(--success);
}

.history-dot.danger {
  color: var(--danger);
}

.history-copy {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.history-copy strong {
  font-size: 12px;
  color: var(--text);
}

.history-copy span {
  font-size: 10.5px;
  color: var(--text-3);
}

.history-row.current .history-copy strong {
  color: var(--accent);
}

.form-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-hint {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  border: 1px dashed var(--border-strong);
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.6;
}

.form-hint svg {
  flex: none;
  margin-top: 2px;
  color: var(--accent);
}

.empty.compact {
  padding: 22px 16px;
}

@media (max-width: 1023px) {
  .kit-hero {
    grid-template-columns: 1fr;
  }
  .checkpoint-grid {
    grid-template-columns: 1fr;
  }
  .kit-row {
    grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) auto 16px;
  }
  .kit-gaps {
    display: none;
  }
}

@media (max-width: 767px) {
  .rate-body {
    flex-direction: column;
    align-items: flex-start;
    padding: 18px;
  }
  .list-head {
    align-items: flex-start;
  }
  .list-head .toolbar {
    width: 100%;
    justify-content: stretch;
  }
  .search-box {
    width: 100%;
  }
  .status-seg {
    width: 100%;
  }
  .kit-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'main badge'
      'score score';
    row-gap: 10px;
    padding: 13px 14px;
  }
  .kit-main {
    grid-area: main;
  }
  .kit-score {
    grid-area: score;
  }
  .kit-row > .badge {
    grid-area: badge;
  }
  .row-arrow {
    display: none;
  }
  .drawer-hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .element-grid {
    grid-template-columns: 1fr;
  }
}
</style>
