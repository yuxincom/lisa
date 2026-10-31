<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ordersApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useUiStore } from '@/stores/ui'
import type { Order, OrderDetail } from '@/types'
import { DOMAIN_COLOR, formatDate, formatDateTime, formatNumber, formatTime } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import PriorityTag from '@/components/PriorityTag.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

interface OrderSummary {
  total: number
  by_status: { status: string; count: number }[]
  by_priority: { priority: string; count: number }[]
  military: number
  kit_risk: number
}

const STATUSES = ['待排产', '已排产', '执行中', '逾期', '已完工', '冻结']
const STATUS_TONE: Record<string, string> = {
  待排产: 'warning',
  已排产: 'blue',
  执行中: 'success',
  逾期: 'danger',
  已完工: 'muted',
  冻结: 'muted',
}

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const summary = ref<OrderSummary | null>(null)
const orders = ref<Order[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')
const priorityFilter = ref('')
const search = ref('')
let searchTimer: number | undefined

const detailOpen = ref(false)
const detail = ref<OrderDetail | null>(null)
const detailLoading = ref(false)
const detailOrderId = ref<number | null>(null)

const countOf = (status: string) => summary.value?.by_status.find((row) => row.status === status)?.count ?? 0
const activityCount = computed(() => countOf('执行中') + countOf('已排产'))
const progressTone = (value: number) => (value >= 80 ? 'var(--success)' : value >= 40 ? 'var(--accent)' : 'var(--blue)')
const kitTone = (status: string) => (status === '齐套' ? 'success' : 'danger')

async function loadSummary() {
  try {
    summary.value = await ordersApi.summary()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const res = await ordersApi.list({
      status: statusFilter.value || undefined,
      priority: priorityFilter.value || undefined,
      search: search.value.trim() || undefined,
      limit: 200,
    })
    orders.value = res.items
    total.value = res.total
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function setStatus(value: string) {
  statusFilter.value = value
  loadOrders()
}

function setPriority(value: string) {
  priorityFilter.value = priorityFilter.value === value ? '' : value
  loadOrders()
}

function onSearch() {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(loadOrders, 280)
}

async function openDetail(order: Order) {
  detailOrderId.value = order.id
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await ordersApi.detail(order.id)
  } catch (err) {
    ui.error('订单详情加载失败', errorMessage(err))
  } finally {
    detailLoading.value = false
  }
  if (route.query.order !== String(order.id)) {
    router.replace({ query: { ...route.query, order: String(order.id) } })
  }
}

function closeDetail() {
  detailOpen.value = false
  detail.value = null
  if (route.query.order) {
    const next = { ...route.query }
    delete next.order
    router.replace({ query: next })
  }
}

function goGantt() {
  if (!detail.value) return
  router.push({ name: 'gantt', query: { search: detail.value.order.order_no } })
}

function goKits() {
  if (!detail.value) return
  router.push({ name: 'kits' })
}

function applyQuery() {
  const id = Number(route.query.order)
  if (id) {
    const found = orders.value.find((item) => item.id === id)
    if (found) openDetail(found)
    else ordersApi.detail(id).then((res) => {
      detail.value = res
      detailOrderId.value = id
      detailOpen.value = true
    }).catch(() => undefined)
  }
}

watch(
  () => route.query.order,
  (value) => {
    if (!value) return
    const id = Number(value)
    if (id && id !== detailOrderId.value) {
      const found = orders.value.find((item) => item.id === id)
      if (found) openDetail(found)
    }
  },
)

onMounted(async () => {
  await Promise.all([loadSummary(), loadOrders()])
  applyQuery()
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L3 · 订单台账"
      title="生产订单全景"
      subtitle="军品保供优先 · 交期、齐套与基线排程一屏掌控"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="loadOrders">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button class="btn btn-teal" type="button" @click="router.push({ name: 'kits' })">
          <AppIcon name="kits" :size="15" />
          齐套检查
        </button>
      </template>
      <template #meta>
        <span>共 {{ summary?.total ?? '—' }} 张订单</span>
        <span class="meta-dot" />
        <span>军品 {{ summary?.military ?? '—' }} 张</span>
        <span class="meta-dot" />
        <span>齐套风险 <strong class="text-danger">{{ summary?.kit_risk ?? '—' }}</strong></span>
      </template>
    </PageHeader>

    <div class="order-stats">
      <div class="stat panel">
        <span class="stat-label">订单总量</span>
        <div class="stat-value num">{{ formatNumber(summary?.total) }}<small>张</small></div>
        <span class="stat-note">覆盖全厂军品与民品任务</span>
      </div>
      <div class="stat panel">
        <span class="stat-label">在制 / 已排</span>
        <div class="stat-value num">{{ formatNumber(activityCount) }}<small>张</small></div>
        <span class="stat-note">执行中 {{ countOf('执行中') }} · 已排产 {{ countOf('已排产') }}</span>
      </div>
      <div class="stat panel tone-danger">
        <span class="stat-label">逾期订单</span>
        <div class="stat-value num">{{ formatNumber(countOf('逾期')) }}<small>张</small></div>
        <span class="stat-note">需在夜间重排中优先保供</span>
      </div>
      <div class="stat panel tone-warning">
        <span class="stat-label">齐套风险</span>
        <div class="stat-value num">{{ formatNumber(summary?.kit_risk) }}<small>张</small></div>
        <span class="stat-note">九要素存在缺口，开工前硬阻断</span>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head filter-head">
        <div class="segmented">
          <button type="button" :class="{ active: !statusFilter }" @click="setStatus('')">
            全部 <span class="seg-count">{{ summary?.total ?? 0 }}</span>
          </button>
          <button
            v-for="status in STATUSES"
            :key="status"
            type="button"
            :class="{ active: statusFilter === status }"
            @click="setStatus(status)"
          >
            {{ status }} <span class="seg-count">{{ countOf(status) }}</span>
          </button>
        </div>
        <div class="toolbar">
          <div class="priority-chips">
            <button
              v-for="item in summary?.by_priority || []"
              :key="item.priority"
              type="button"
              class="priority"
              :class="[`priority-${item.priority}`, { dim: priorityFilter && priorityFilter !== item.priority }]"
              @click="setPriority(item.priority)"
            >
              {{ item.priority }} <span>{{ item.count }}</span>
            </button>
          </div>
          <div class="search-box">
            <AppIcon name="search" :size="14" />
            <input v-model="search" class="input" placeholder="订单号 / 产品 / 客户" @input="onSearch" />
          </div>
        </div>
      </div>

      <div v-if="error" class="empty">
        <AppIcon name="alert" :size="22" />
        {{ error }}
      </div>
      <div v-else-if="loading" class="order-loading"><span class="spinner" /> 正在加载订单…</div>

      <div v-else-if="orders.length" class="order-list">
        <div class="order-list-head hide-mobile">
          <span>订单 / 产品</span>
          <span>优先级</span>
          <span>交期</span>
          <span>基线排程</span>
          <span>状态</span>
          <span>齐套</span>
          <span class="align-right">进度</span>
        </div>
        <button
          v-for="order in orders"
          :key="order.id"
          type="button"
          class="order-row"
          @click="openDetail(order)"
        >
          <div class="order-main">
            <span class="order-no mono">{{ order.order_no }}</span>
            <strong class="order-name">{{ order.product_name }}</strong>
            <span class="order-meta">
              {{ order.customer }} · {{ order.plant }} · 数量 {{ order.qty }}
              <span v-if="order.is_military" class="badge badge-accent">军品</span>
            </span>
            <span class="order-mobile-tags only-mobile">
              <StatusBadge :status="order.status" :tone="STATUS_TONE[order.status]" />
              <span class="badge badge-muted">交期 {{ formatDate(order.due_date) }}</span>
              <span class="badge" :class="`badge-${kitTone(order.kit_status)}`">{{ order.kit_status }}</span>
              <span v-if="(order.late_hours || 0) > 0" class="badge badge-danger">逾期 {{ order.late_hours }}h</span>
            </span>
          </div>
          <div class="order-priority"><PriorityTag :priority="order.priority" /></div>
          <div class="order-cell">
            <span class="cell-label">交期</span>
            <strong>{{ formatDate(order.due_date) }}</strong>
          </div>
          <div class="order-cell">
            <span class="cell-label">基线完成</span>
            <strong :class="{ 'text-danger': (order.late_hours || 0) > 0 }">
              {{ formatDate(order.scheduled_finish) }}
            </strong>
            <span v-if="(order.late_hours || 0) > 0" class="late-tag">逾期 {{ order.late_hours }}h</span>
            <span v-else-if="order.scheduled_finish" class="muted">按计划</span>
          </div>
          <div class="order-status">
            <StatusBadge :status="order.status" :tone="STATUS_TONE[order.status]" />
          </div>
          <div class="order-kit">
            <span class="badge" :class="`badge-${kitTone(order.kit_status)}`">
              <span class="dot" />{{ order.kit_status }}
            </span>
          </div>
          <div class="order-progress">
            <div class="progress"><i :style="{ width: `${order.progress}%`, background: progressTone(order.progress) }" /></div>
            <span class="num">{{ order.progress }}%</span>
          </div>
          <AppIcon name="chevron-right" :size="15" class="row-arrow hide-mobile" />
        </button>
      </div>

      <div v-else class="empty">
        <div class="empty-icon"><AppIcon name="orders" :size="20" /></div>
        当前筛选条件下暂无订单
      </div>

      <div v-if="orders.length && total > orders.length" class="panel-foot">
        已显示 {{ orders.length }} / {{ total }} 张订单，可使用搜索缩小范围
      </div>
    </section>

    <BaseDrawer
      :model-value="detailOpen"
      width="720px"
      :title="detail ? detail.order.order_no : '订单详情'"
      :subtitle="detail?.order.product_name || '正在加载订单…'"
      @update:model-value="closeDetail"
    >
      <div v-if="detailLoading" class="order-loading"><span class="spinner" /> 正在加载订单详情…</div>
      <template v-else-if="detail">
        <div class="detail-hero">
          <div class="hero-top">
            <div class="hero-tags">
              <PriorityTag :priority="detail.order.priority" />
              <StatusBadge :status="detail.order.status" :tone="STATUS_TONE[detail.order.status]" />
              <span class="badge" :class="`badge-${kitTone(detail.order.kit_status)}`">
                <span class="dot" />齐套 {{ detail.order.kit_status }}
              </span>
              <span v-if="detail.order.is_military" class="badge badge-accent">军品保供</span>
            </div>
            <span class="hero-progress num">{{ detail.order.progress }}%</span>
          </div>
          <div class="progress hero-bar">
            <i :style="{ width: `${detail.order.progress}%`, background: progressTone(detail.order.progress) }" />
          </div>
          <div class="hero-grid">
            <div><span>客户</span><strong>{{ detail.order.customer }}</strong></div>
            <div><span>厂区</span><strong>{{ detail.order.plant }}</strong></div>
            <div><span>数量</span><strong class="num">{{ detail.order.qty }}</strong></div>
            <div><span>交期</span><strong>{{ formatDate(detail.order.due_date) }}</strong></div>
            <div><span>基线开工</span><strong>{{ formatDateTime(detail.order.scheduled_start) }}</strong></div>
            <div>
              <span>基线完成</span>
              <strong :class="{ 'text-danger': (detail.order.late_hours || 0) > 0 }">
                {{ formatDateTime(detail.order.scheduled_finish) }}
              </strong>
            </div>
            <div><span>投料时间</span><strong>{{ formatDateTime(detail.order.released_at) }}</strong></div>
            <div><span>工序数</span><strong class="num">{{ detail.operations.length }}</strong></div>
          </div>
        </div>

        <h4 class="section-title">
          工序路线
          <span class="section-note">{{ detail.operations.length }} 道工序</span>
        </h4>
        <div class="op-list">
          <div v-for="op in detail.operations" :key="op.id" class="op-row">
            <span class="op-seq num">{{ String(op.seq).padStart(2, '0') }}</span>
            <span class="op-dot" :style="{ background: DOMAIN_COLOR[op.domain] || 'var(--text-3)' }" />
            <div class="op-copy">
              <div class="op-title">
                <strong>{{ op.name }}</strong>
                <span class="badge badge-muted">{{ op.domain }}</span>
                <span v-if="op.special" class="badge badge-violet">特殊过程</span>
                <span v-if="op.locked" class="badge badge-warning">冻结锁定</span>
                <span v-if="op.risk === 'late'" class="badge badge-danger">逾期风险</span>
              </div>
              <span class="op-meta">
                {{ op.resource || '未分配设备' }} · 标准 {{ op.std_minutes }}min · 准备 {{ op.setup_minutes }}min
              </span>
            </div>
            <div class="op-time">
              <span>{{ formatDateTime(op.planned_start) }}</span>
              <span class="muted">→ {{ formatTime(op.planned_end) }}</span>
            </div>
          </div>
        </div>

        <h4 class="section-title">
          齐套状态
          <span class="section-note">最新时点快照</span>
        </h4>
        <div v-if="detail.kits.length" class="kit-grid">
          <div v-for="kit in detail.kits" :key="kit.id" class="kit-card">
            <div class="kit-card-head">
              <strong>{{ kit.checkpoint_label }}</strong>
              <StatusBadge :status="kit.status" />
            </div>
            <div class="kit-card-score"><span class="num">{{ kit.score }}%</span> 齐套度</div>
            <div class="progress thin"><i :style="{ width: `${kit.score}%` }" /></div>
            <span class="kit-card-time">{{ formatDateTime(kit.checked_at) }}</span>
          </div>
        </div>
        <div v-else class="empty compact">该订单暂无齐套检查记录</div>
      </template>

      <template #footer>
        <button class="btn btn-ghost" type="button" @click="goKits">
          <AppIcon name="kits" :size="14" />
          齐套校验台
        </button>
        <button class="btn btn-primary" type="button" @click="goGantt">
          <AppIcon name="gantt" :size="14" />
          在甘特中查看
        </button>
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

.order-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stat {
  padding: 16px 18px;
  position: relative;
}

.stat::before {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent);
  opacity: 0.8;
}

.stat.tone-danger::before {
  background: var(--danger);
}

.stat.tone-warning::before {
  background: var(--warning);
}

.stat-label {
  font-size: 11.5px;
  color: var(--text-3);
  letter-spacing: 0.04em;
}

.stat-value {
  font-family: var(--font-display);
  font-size: 27px;
  font-weight: 700;
  line-height: 1.25;
  margin: 4px 0 2px;
}

.stat-value small {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-3);
  margin-left: 4px;
}

.stat-note {
  font-size: 11px;
  color: var(--text-3);
}

.filter-head {
  flex-wrap: wrap;
}

@media (max-width: 767px) {
  .filter-head .segmented {
    flex-wrap: wrap;
    overflow-x: visible;
  }
}

.filter-head .toolbar {
  flex: 1;
  justify-content: flex-end;
}

.seg-count {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.7;
}

.priority-chips {
  display: flex;
  gap: 5px;
}

.priority-chips .priority {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: opacity 0.16s ease;
}

.priority-chips .priority span {
  font-size: 9.5px;
  opacity: 0.75;
}

.priority-chips .priority.dim {
  opacity: 0.45;
}

.search-box {
  width: 220px;
}

.order-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 42px 16px;
  font-size: 12.5px;
  color: var(--text-3);
}

.order-list-head {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) 58px 92px minmax(0, 1fr) 76px 70px 120px;
  gap: 14px;
  padding: 10px 18px;
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel-solid) 92%, transparent);
}

.order-list-head .align-right {
  text-align: right;
}

.order-row {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) 58px 92px minmax(0, 1fr) 76px 70px 120px 16px;
  gap: 14px;
  align-items: center;
  width: 100%;
  padding: 13px 18px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  text-align: left;
  transition: background-color 0.15s ease;
}

.order-list-head {
  grid-template-columns: minmax(0, 2.1fr) 58px 92px minmax(0, 1fr) 76px 70px 120px 16px;
}

.order-row:last-child {
  border-bottom: 0;
}

.order-row:hover {
  background: color-mix(in srgb, var(--panel-strong) 62%, transparent);
}

.order-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.order-no {
  font-size: 11px;
  color: var(--accent);
}

.order-name {
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.8px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.order-cell strong {
  font-weight: 600;
  color: var(--text);
}

.cell-label {
  display: none;
  font-size: 10.5px;
  color: var(--text-3);
}

.late-tag {
  font-size: 10px;
  color: var(--danger);
}

.order-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-2);
}

.order-progress .progress {
  flex: 1;
}

.row-arrow {
  color: var(--text-3);
}

.detail-hero {
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-inset);
  margin-bottom: 20px;
}

.hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.hero-progress {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--accent);
}

.hero-bar {
  height: 5px;
  margin-bottom: 14px;
}

.hero-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.hero-grid div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.hero-grid span {
  font-size: 10.5px;
  color: var(--text-3);
}

.hero-grid strong {
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  margin: 20px 0 10px;
}

.section-title:first-of-type {
  margin-top: 0;
}

.section-note {
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

.op-list {
  display: flex;
  flex-direction: column;
}

.op-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.op-row:last-child {
  border-bottom: 0;
}

.op-seq {
  font-size: 11px;
  color: var(--text-3);
  width: 20px;
  flex: none;
}

.op-dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex: none;
}

.op-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.op-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.op-title strong {
  font-size: 12.5px;
  color: var(--text);
  font-weight: 600;
}

.op-title .badge {
  height: 18px;
  font-size: 9.5px;
  padding: 0 6px;
}

.op-meta {
  font-size: 10.5px;
  color: var(--text-3);
}

.op-time {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 10.5px;
  color: var(--text-2);
  white-space: nowrap;
  flex: none;
}

.kit-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.kit-card {
  padding: 11px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.kit-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 7px;
}

.kit-card-head strong {
  font-size: 12px;
  color: var(--text);
}

.kit-card-score {
  font-size: 10.5px;
  color: var(--text-3);
  margin-bottom: 6px;
}

.kit-card-score .num {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-right: 3px;
}

.kit-card-time {
  display: block;
  margin-top: 7px;
  font-size: 10px;
  color: var(--text-3);
}

.progress.thin {
  height: 4px;
}

.empty.compact {
  padding: 20px 14px;
}

@media (max-width: 1279px) {
  .order-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .order-list-head,
  .order-row {
    grid-template-columns: minmax(0, 1.8fr) 54px 88px minmax(0, 1fr) 74px 68px 100px 16px;
    gap: 10px;
  }
}

@media (max-width: 1023px) {
  .order-list-head,
  .order-row {
    grid-template-columns: minmax(0, 1.7fr) 54px 90px 74px 16px;
  }
  .order-cell:nth-of-type(4),
  .order-kit,
  .order-progress,
  .order-list-head > span:nth-child(5),
  .order-list-head > span:nth-child(6),
  .order-list-head > span:nth-child(7) {
    display: none;
  }
  .hero-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .kit-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .order-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .stat {
    padding: 13px 14px;
  }
  .stat-value {
    font-size: 22px;
  }
  .filter-head {
    flex-direction: column;
    align-items: stretch;
  }
  .filter-head .toolbar {
    flex-wrap: wrap;
  }
  .search-box {
    width: 100%;
  }
  .priority-chips {
    width: 100%;
    justify-content: flex-start;
  }
  .order-list-head {
    display: none;
  }
  .order-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'main priority'
      'meta meta';
    gap: 8px 12px;
    padding: 13px 14px;
  }
  .order-main {
    grid-area: main;
  }
  .order-main .order-meta {
    white-space: normal;
    flex-wrap: wrap;
  }
  .order-priority {
    grid-area: priority;
    align-self: start;
  }
  .order-cell,
  .order-status,
  .order-kit,
  .order-progress,
  .row-arrow {
    display: none;
  }
  .order-mobile-tags {
    display: flex !important;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 5px;
  }
  .op-row {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .op-time {
    width: 100%;
    flex-direction: row;
    justify-content: flex-end;
    gap: 6px;
    padding-left: 37px;
  }
  .detail-hero {
    padding: 14px;
  }
  .hero-grid {
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
}
</style>
