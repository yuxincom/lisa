<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { plansApi } from '@/api'
import { useUiStore } from '@/stores/ui'
import type { Plan, PlanItem, Resource } from '@/types'
import {
  DOMAIN_COLOR,
  DOMAINS,
  PRIORITY_LABEL,
  RISK_LABEL,
  SCENARIO_LABEL,
  formatDateTime,
  formatHours,
  formatNumber,
  formatTime,
  statusTone,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

type GanttData = Awaited<ReturnType<typeof plansApi.gantt>>
type LaidItem = PlanItem & { lane: number }

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const DAY = 86_400_000
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const RAIL_WIDTH = 206

const plans = ref<Plan[]>([])
const baselineId = ref<number | null>(null)
const planId = ref<number | null>(null)
const gantt = ref<GanttData | null>(null)
const loading = ref(false)
const error = ref('')
const domain = ref('机加')
const priority = ref('')
const search = ref('')
const dayWidth = ref(148)
const viewMode = ref<'gantt' | 'list'>('gantt')
const selected = ref<PlanItem | null>(null)
const drawerOpen = ref(false)
const mobileQuery = window.matchMedia('(max-width: 767px)')

if (mobileQuery.matches) viewMode.value = 'list'
const onMobileChange = (event: MediaQueryListEvent) => {
  viewMode.value = event.matches ? 'list' : 'gantt'
}
mobileQuery.addEventListener('change', onMobileChange)

let requestSeq = 0
let searchTimer: number | null = null

const planOptions = computed(() =>
  plans.value.filter((plan) => ['applied', 'approved', 'pending'].includes(plan.status)),
)
const currentPlan = computed(() => gantt.value?.plan || plans.value.find((plan) => plan.id === planId.value) || null)
const isBaseline = computed(() => planId.value !== null && planId.value === baselineId.value)

function pickInitialPlan(): number | null {
  const queryId = Number(route.query.plan)
  if (Number.isFinite(queryId) && queryId > 0) return queryId
  return baselineId.value || planOptions.value[0]?.id || plans.value[0]?.id || null
}

async function bootstrap() {
  try {
    const [list, base] = await Promise.all([
      plansApi.list({ limit: 40 }),
      plansApi.baseline().catch(() => null),
    ])
    plans.value = list.items
    baselineId.value = base?.id ?? null
    planId.value = pickInitialPlan()
    if (planId.value) await loadGantt()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '排产数据加载失败'
  }
}

async function loadGantt() {
  if (!planId.value) return
  const token = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const response = await plansApi.gantt(planId.value, {
      domain: domain.value,
      search: search.value.trim() || undefined,
      priority: priority.value || undefined,
    })
    if (token !== requestSeq) return
    gantt.value = response
  } catch (err) {
    if (token !== requestSeq) return
    error.value = err instanceof Error ? err.message : '甘特数据加载失败'
  } finally {
    if (token === requestSeq) loading.value = false
  }
}

function selectPlan(id: number) {
  planId.value = id
  router.replace({ query: { ...route.query, plan: String(id) } })
  void loadGantt()
}

function refresh() {
  void loadGantt()
}

function resetFilters() {
  priority.value = ''
  search.value = ''
  domain.value = '机加'
}

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => void loadGantt(), 320)
}

watch(domain, () => void loadGantt())
watch(priority, () => void loadGantt())
watch(
  () => route.query.plan,
  (value) => {
    const id = Number(value)
    if (Number.isFinite(id) && id > 0 && id !== planId.value) {
      planId.value = id
      void loadGantt()
    }
  },
)

onMounted(() => void bootstrap())
onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
  mobileQuery.removeEventListener('change', onMobileChange)
})

/* ---------- timeline geometry ---------- */
function startOfDay(date: Date): Date {
  const copy = new Date(date)
  copy.setHours(0, 0, 0, 0)
  return copy
}

const range = computed(() => {
  const items = gantt.value?.items || []
  const now = gantt.value?.now ? new Date(gantt.value.now) : new Date()
  const freezeEnd = gantt.value?.freeze_until ? new Date(gantt.value.freeze_until) : new Date(now.getTime() + 3 * DAY)
  let min = startOfDay(now)
  let max = new Date(startOfDay(freezeEnd).getTime() + DAY)
  for (const item of items) {
    const start = startOfDay(new Date(item.start))
    const end = new Date(item.end).getTime()
    if (start.getTime() < min.getTime()) min = start
    if (end > max.getTime()) max = new Date(end)
  }
  if (max.getTime() - min.getTime() < 6 * DAY) max = new Date(min.getTime() + 6 * DAY)
  if (max.getTime() - min.getTime() > 21 * DAY) max = new Date(min.getTime() + 21 * DAY)
  return {
    start: min.getTime(),
    end: Math.ceil(max.getTime() / DAY) * DAY + DAY,
    now: now.getTime(),
    freezeEnd: freezeEnd.getTime(),
  }
})

const days = computed(() => {
  const list: { date: Date; key: string; today: boolean; weekend: boolean }[] = []
  const nowKey = startOfDay(new Date()).getTime()
  for (let time = range.value.start; time < range.value.end; time += DAY) {
    const date = new Date(time)
    list.push({
      date,
      key: `${date.getMonth() + 1}-${date.getDate()}`,
      today: time === nowKey,
      weekend: date.getDay() === 0 || date.getDay() === 6,
    })
  }
  return list
})

const trackWidth = computed(() => days.value.length * dayWidth.value)

function leftPx(input: string | number): number {
  const time = typeof input === 'number' ? input : new Date(input).getTime()
  return ((time - range.value.start) / DAY) * dayWidth.value
}

const freezeStyle = computed(() => {
  const start = Math.max(range.value.start, range.value.now)
  const end = Math.min(range.value.end, range.value.freezeEnd)
  if (end <= start) return { display: 'none' }
  return {
    left: `${leftPx(start)}px`,
    width: `${Math.max(2, ((end - start) / DAY) * dayWidth.value)}px`,
  }
})

const nowStyle = computed(() => {
  if (range.value.now < range.value.start || range.value.now > range.value.end) return { display: 'none' }
  return { left: `${leftPx(range.value.now)}px` }
})

/* ---------- rows ---------- */
const rows = computed(() => {
  const items = gantt.value?.items || []
  const resources: Resource[] = gantt.value?.resources || []
  const grouped = new Map<number, PlanItem[]>()
  for (const item of items) {
    const bucket = grouped.get(item.resource_id) || []
    bucket.push(item)
    grouped.set(item.resource_id, bucket)
  }
  return resources.map((resource) => {
    const list = [...(grouped.get(resource.id) || [])].sort(
      (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
    )
    const laneEnds: number[] = []
    const laid: LaidItem[] = list.map((item) => {
      const start = new Date(item.start).getTime()
      const end = new Date(item.end).getTime()
      let lane = laneEnds.findIndex((value) => value <= start)
      if (lane < 0) {
        lane = laneEnds.length
        laneEnds.push(end)
      } else {
        laneEnds[lane] = end
      }
      return { ...item, lane }
    })
    const lanes = Math.max(1, laneEnds.length)
    const minutes = list.reduce((sum, item) => sum + item.duration_minutes, 0)
    return {
      resource,
      items: laid,
      lanes,
      height: Math.max(74, lanes * 27 + 16),
      hours: minutes / 60,
    }
  })
})

const baselineStarts = computed(() => {
  const map = new Map<number, string>()
  for (const item of gantt.value?.baseline_items || []) map.set(item.operation_id, item.start)
  return map
})

const shownItems = computed(() => [...(gantt.value?.items || [])].sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime()))

type RowMetrics = { height: number; lanes: number }

function laneTop(row: RowMetrics): number {
  return Math.max(5, Math.round((row.height - row.lanes * 27) / 2))
}

function barStyle(item: LaidItem, row: RowMetrics) {
  const start = new Date(item.start).getTime()
  const end = new Date(item.end).getTime()
  const color = DOMAIN_COLOR[item.domain] || 'var(--accent)'
  return {
    left: `${leftPx(start)}px`,
    width: `${Math.max(5, ((end - start) / DAY) * dayWidth.value)}px`,
    top: `${laneTop(row) + item.lane * 27}px`,
    background: item.risk === 'late' ? 'var(--danger)' : color,
  }
}

function ghostStyle(item: LaidItem, row: RowMetrics) {
  return {
    left: `${leftPx(item.start)}px`,
    top: `${laneTop(row) + item.lane * 27}px`,
  }
}

function barWidth(item: LaidItem): number {
  return Math.max(5, ((new Date(item.end).getTime() - new Date(item.start).getTime()) / DAY) * dayWidth.value)
}

function itemTitle(item: PlanItem): string {
  return `${item.order_no} · ${item.name}\n${formatDateTime(item.start)} → ${formatTime(item.end)}\n${item.resource_code} ${item.resource_name}`
}

const baselineDiff = computed(() => {
  if (!selected.value) return null
  const baselineStart = baselineStarts.value.get(selected.value.operation_id)
  if (!baselineStart) return null
  const delta = (new Date(selected.value.start).getTime() - new Date(baselineStart).getTime()) / 3_600_000
  if (Math.abs(delta) < 0.05) return { delta: 0, baselineStart }
  return { delta, baselineStart }
})

function openItem(item: PlanItem) {
  selected.value = item
  drawerOpen.value = true
}

function closeDrawer() {
  drawerOpen.value = false
  selected.value = null
}

function formatMinutes(value: number | undefined | null): string {
  if (!value) return '0 min'
  return `${Math.round(value)} min`
}

function gotoOrder(orderId: number) {
  closeDrawer()
  router.push({ path: '/orders', query: { order: orderId } })
}

function zoom(direction: 'in' | 'out') {
  dayWidth.value = Math.min(320, Math.max(96, dayWidth.value + (direction === 'in' ? 28 : -28)))
}

const stats = computed(() => {
  const s = gantt.value?.stats
  return [
    { label: '工序', value: formatNumber(s?.operations ?? 0), icon: 'route', tone: '' },
    { label: '订单', value: formatNumber(s?.orders ?? 0), icon: 'orders', tone: '' },
    { label: '逾期', value: formatNumber(s?.late ?? 0), icon: 'warning', tone: s?.late ? 'danger' : '' },
    { label: '紧张', value: formatNumber(s?.tight ?? 0), icon: 'clock', tone: s?.tight ? 'warning' : '' },
    { label: '冻结锁定', value: formatNumber(s?.locked ?? 0), icon: 'lock', tone: 'teal' },
    { label: '瓶颈资源', value: formatNumber(s?.bottleneck ?? 0), icon: 'cpu', tone: s?.bottleneck ? 'accent' : '' },
  ]
})

const empty = computed(() => !loading.value && gantt.value !== null && shownItems.value.length === 0)
</script>

<template>
  <div class="page gantt-page">
    <PageHeader
      eyebrow="FINITE CAPACITY · 决策层"
      title="智能排产"
      subtitle="有限产能资源甘特、冻结窗口与基线偏差同屏对照。所有写入 APS/MES 的动作均受写保护网关与电子签名约束。"
    >
      <template #actions>
        <select
          class="select plan-select"
          :value="planId ?? ''"
          @change="selectPlan(Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="plan in planOptions" :key="plan.id" :value="plan.id">
            {{ plan.code }} · {{ plan.scenario }} · {{ plan.status_label }}
          </option>
        </select>
        <button class="btn btn-sm" @click="refresh">
          <span v-if="loading" class="spinner" /><AppIcon v-else name="refresh" :size="15" />
          刷新
        </button>
        <router-link class="btn btn-sm btn-primary" to="/plans">
          <AppIcon name="signature" :size="15" />
          方案审批
        </router-link>
      </template>
      <template #meta>
        <div class="flex items-center gap-10 fs-12 muted wrap">
          <span class="flex items-center gap-6">
            <span class="dot dot-live" />
            {{ isBaseline ? '当前生效基线' : '方案预览（未签发）' }}
          </span>
          <span v-if="gantt" class="mono">{{ gantt.plan.code }}</span>
          <span v-if="gantt" class="hide-mobile">冻结至 {{ formatDateTime(gantt.freeze_until) }}</span>
        </div>
      </template>
    </PageHeader>

    <section class="gantt-stats">
      <div v-for="item in stats" :key="item.label" class="gstat" :class="`tone-${item.tone}`">
        <span class="gstat-icon"><AppIcon :name="item.icon" :size="15" /></span>
        <div>
          <strong class="num">{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </div>
      </div>
      <div class="gstat-plan">
        <span class="badge" :class="`badge-${statusTone(currentPlan?.status)}`">{{ currentPlan?.status_label || '—' }}</span>
        <span v-if="currentPlan" class="badge badge-muted">{{ SCENARIO_LABEL[currentPlan.scenario] || currentPlan.scenario }}</span>
        <span v-if="currentPlan" class="fs-12 muted">准时率 {{ currentPlan.kpi?.on_time_rate?.toFixed(1) }}% · 评分 {{ currentPlan.kpi?.total_score?.toFixed(1) }}</span>
      </div>
    </section>

    <section class="panel gantt-panel">
      <div class="gantt-toolbar">
        <div class="segmented domain-tabs">
          <button
            v-for="name in DOMAINS"
            :key="name"
            :class="{ active: domain === name }"
            @click="domain = name"
          >
            <i class="domain-dot" :style="{ background: DOMAIN_COLOR[name] }" />
            {{ name }}
          </button>
        </div>
        <div class="toolbar-actions">
          <div class="search-box gantt-search">
            <AppIcon name="search" :size="14" />
            <input v-model="search" class="input" placeholder="订单 / 产品 / 工序" @input="onSearchInput" />
          </div>
          <div class="segmented priority-tabs">
            <button :class="{ active: !priority }" @click="priority = ''">全部</button>
            <button v-for="level in ['P0', 'P1', 'P2']" :key="level" :class="{ active: priority === level }" @click="priority = level">
              {{ level }}
            </button>
          </div>
          <div class="segmented view-tabs">
            <button :class="{ active: viewMode === 'gantt' }" @click="viewMode = 'gantt'">
              <AppIcon name="gantt" :size="13" /> 甘特
            </button>
            <button :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'">
              <AppIcon name="list" :size="13" /> 列表
            </button>
          </div>
          <div class="zoom">
            <button class="btn btn-sm btn-icon" aria-label="缩小" @click="zoom('out')"><AppIcon name="chevronLeft" :size="14" /></button>
            <button class="btn btn-sm btn-icon" aria-label="放大" @click="zoom('in')"><AppIcon name="chevronRight" :size="14" /></button>
          </div>
        </div>
      </div>

      <div v-if="error" class="inline-error">
        <AppIcon name="warning" :size="16" />
        {{ error }}
        <button class="btn btn-sm" @click="refresh">重试</button>
      </div>

      <div v-if="viewMode === 'gantt'" class="gantt-wrap">
        <div class="gantt-legend">
          <div class="legend">
            <span v-for="name in DOMAINS" :key="name"><i :style="{ background: DOMAIN_COLOR[name] }" />{{ name }}</span>
            <span><i style="background: var(--danger)" />逾期</span>
            <span><i style="background: var(--accent-soft); border: 1px dashed var(--accent)" />冻结窗口</span>
            <span><i style="background: var(--text-3)" />基线位置</span>
          </div>
          <span class="fs-12 muted">← 横向滚动查看 · 点击作业查看白盒归因</span>
        </div>

        <div class="gantt-scroll">
          <div class="gantt-inner" :style="{ width: `${RAIL_WIDTH + trackWidth}px` }">
            <div class="gantt-header">
              <div class="rail-cell corner" :style="{ width: `${RAIL_WIDTH}px` }">
                <span>资源 / 日期</span>
                <span class="corner-sub">{{ domain }}域 · {{ rows.length }} 资源</span>
              </div>
              <div class="day-head" :style="{ width: `${trackWidth}px` }">
                <div
                  v-for="day in days"
                  :key="day.key"
                  class="day-cell"
                  :class="{ today: day.today, weekend: day.weekend }"
                  :style="{ width: `${dayWidth}px` }"
                >
                  <span class="day-num">{{ day.date.getDate() }}</span>
                  <span class="day-sub">{{ WEEKDAYS[day.date.getDay()] }}</span>
                  <span class="day-month">{{ day.date.getMonth() + 1 }}月</span>
                </div>
              </div>
            </div>

            <div class="gantt-rows" :class="{ loading }">
              <div v-for="row in rows" :key="row.resource.id" class="gantt-row" :style="{ height: `${row.height}px` }">
                <div class="rail-cell rail" :class="{ bottleneck: row.resource.bottleneck }" :style="{ width: `${RAIL_WIDTH}px` }">
                  <div class="rail-top">
                    <span class="rail-code mono">{{ row.resource.code }}</span>
                    <span v-if="row.resource.bottleneck" class="badge badge-danger">瓶颈</span>
                    <span v-else-if="row.resource.status === 'maintenance'" class="badge badge-warning">检修</span>
                  </div>
                  <div class="rail-name truncate">{{ row.resource.name }}</div>
                  <div class="rail-meta num">{{ formatNumber(row.hours, 1) }}h · {{ row.items.length }} 工序 · {{ Math.round(row.resource.efficiency * 100) }}%</div>
                </div>
                <div
                  class="track"
                  :style="{ width: `${trackWidth}px`, backgroundSize: `${dayWidth}px 100%` }"
                >
                  <div class="freeze-band" :style="freezeStyle" />
                  <div class="now-line" :style="nowStyle" />
                  <template v-for="item in row.items" :key="item.id">
                    <span
                      v-if="baselineStarts.has(item.operation_id)"
                      class="baseline-tick"
                      :style="ghostStyle(item, row)"
                      :title="`基线开始 ${formatDateTime(baselineStarts.get(item.operation_id) || '')}`"
                    />
                    <button
                      class="gantt-bar"
                      :class="{ late: item.risk === 'late', tight: item.risk === 'tight', locked: item.locked }"
                      :style="barStyle(item, row)"
                      :title="itemTitle(item)"
                      @click="openItem(item)"
                    >
                      <span v-if="barWidth(item) > 74" class="bar-text">{{ item.order_no }} · {{ item.name }}</span>
                      <span v-if="item.locked" class="bar-lock"><AppIcon name="lock" :size="9" /></span>
                    </button>
                  </template>
                </div>
              </div>
              <div v-if="empty" class="empty">
                <span class="empty-icon"><AppIcon name="gantt" :size="22" /></span>
                当前筛选条件下无排产作业
                <button class="btn btn-sm" @click="resetFilters">清除筛选</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="gantt-list">
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>订单</th>
                <th>工序</th>
                <th>优先级</th>
                <th>资源</th>
                <th>开始</th>
                <th>结束</th>
                <th>工时</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in shownItems" :key="item.id" @click="openItem(item)">
                <td class="cell-strong mono">{{ item.order_no }}</td>
                <td>
                  {{ item.name }}
                  <div class="fs-12 muted truncate">{{ item.product_name }}</div>
                </td>
                <td><span class="priority" :class="`priority-${item.priority}`">{{ item.priority }}</span></td>
                <td>{{ item.resource_code }}<div class="fs-12 muted">{{ item.resource_name }}</div></td>
                <td>{{ formatDateTime(item.start) }}</td>
                <td>{{ formatTime(item.end) }}</td>
                <td class="num">{{ formatHours(item.duration_minutes) }}</td>
                <td>
                  <StatusBadge :status="item.risk" :label="item.locked ? '冻结锁定' : RISK_LABEL[item.risk] || '正常'" :tone="item.locked ? 'teal' : undefined" />
                </td>
              </tr>
              <tr v-if="!shownItems.length">
                <td colspan="8"><div class="empty">{{ loading ? '加载中…' : '当前筛选条件下无排产作业' }}</div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="gantt-foot">
        <span>冻结窗口 {{ gantt ? formatDateTime(gantt.freeze_until) : '—' }} 内作业锁定基线，求解器不可移动</span>
        <span v-if="gantt" class="mono">SOLVER · {{ gantt.plan.summary?.solver || 'LISA Heuristic Engine' }}</span>
      </div>
    </section>

    <BaseDrawer v-model="drawerOpen" width="560px">
      <template #header>
        <div v-if="selected" class="drawer-title-block">
          <span class="drawer-domain" :style="{ background: DOMAIN_COLOR[selected.domain] }" />
          <div>
            <h3 class="drawer-title">{{ selected.order_no }} · {{ selected.name }}</h3>
            <p class="drawer-sub">{{ selected.product_name }} · Seq {{ selected.seq }}</p>
          </div>
        </div>
      </template>

      <template v-if="selected">
        <div class="detail-tags">
          <span class="priority" :class="`priority-${selected.priority}`">{{ PRIORITY_LABEL[selected.priority] || selected.priority }}</span>
          <span class="badge" :class="`badge-${selected.risk === 'late' ? 'danger' : selected.risk === 'tight' ? 'warning' : 'teal'}`">
            {{ RISK_LABEL[selected.risk] || '正常' }}
          </span>
          <span v-if="selected.locked" class="badge badge-blue"><AppIcon name="lock" :size="11" /> 冻结锁定</span>
          <span class="badge badge-muted">{{ selected.domain }}</span>
        </div>

        <div class="detail-grid">
          <div class="detail-cell">
            <span>计划开始</span>
            <strong>{{ formatDateTime(selected.start) }}</strong>
          </div>
          <div class="detail-cell">
            <span>计划结束</span>
            <strong>{{ formatDateTime(selected.end) }}</strong>
          </div>
          <div class="detail-cell">
            <span>加工工时</span>
            <strong>{{ formatHours(selected.duration_minutes) }}</strong>
          </div>
          <div class="detail-cell">
            <span>换型 / 准备</span>
            <strong>{{ formatMinutes(selected.setup_minutes) }}</strong>
          </div>
          <div class="detail-cell">
            <span>占用资源</span>
            <strong>{{ selected.resource_code }}</strong>
          </div>
          <div class="detail-cell">
            <span>资源名称</span>
            <strong>{{ selected.resource_name }}</strong>
          </div>
        </div>

        <div class="drawer-section">
          <div class="section-title"><AppIcon name="spark" :size="14" /> 白盒归因</div>
          <p class="reason-text">{{ selected.reason || '由有限产能引擎按交期与优先级顺排' }}</p>
        </div>

        <div class="drawer-section">
          <div class="section-title"><AppIcon name="activity" :size="14" /> 相对基线偏差</div>
          <div v-if="baselineDiff" class="baseline-diff" :class="{ advanced: baselineDiff.delta < 0 }">
            <span class="bd-value num">
              {{ baselineDiff.delta > 0 ? '+' : '' }}{{ baselineDiff.delta.toFixed(1) }}h
            </span>
            <div>
              <div class="bd-label">{{ baselineDiff.delta === 0 ? '与基线一致' : baselineDiff.delta > 0 ? '较基线推迟' : '较基线提前' }}</div>
              <div class="fs-12 muted">基线开始 {{ formatDateTime(baselineDiff.baselineStart) }}</div>
            </div>
          </div>
          <div v-else class="fs-12 muted">该工序在基线中无对应记录，属于新增作业。</div>
        </div>

        <div class="drawer-section">
          <div class="section-title"><AppIcon name="shield" :size="14" /> 约束与写保护</div>
          <div class="kv"><span class="k">硬约束校验</span><span class="v text-success">HC-12 工序依赖闭环通过</span></div>
          <div class="kv"><span class="k">资源能力</span><span class="v">HC-09 能力域匹配</span></div>
          <div class="kv"><span class="k">写入通道</span><span class="v text-warning">仅经审批签名后写入 APS/MES</span></div>
        </div>
      </template>

      <template #footer>
        <button class="btn btn-ghost" @click="closeDrawer">关闭</button>
        <button v-if="selected" class="btn btn-teal" @click="gotoOrder(selected.order_id)">
          <AppIcon name="orders" :size="14" /> 查看订单链路
        </button>
      </template>
    </BaseDrawer>
  </div>
</template>

<style scoped>
.gantt-page { display: flex; flex-direction: column; gap: 14px; }
.gantt-page :deep(.page-header) { margin-bottom: 2px; }

.plan-select {
  width: 280px;
  min-height: 34px;
  font-family: var(--mono);
  font-size: 11.5px;
}

.gantt-stats {
  display: flex;
  gap: 10px;
  align-items: stretch;
  flex-wrap: wrap;
}
.gstat {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 13px;
  min-width: 112px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
}
.gstat-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--panel-inset);
  color: var(--text-3);
  flex: none;
}
.gstat strong {
  display: block;
  font-size: 18px;
  line-height: 1.15;
}
.gstat span:last-child {
  font-size: 10.5px;
  color: var(--text-3);
}
.gstat.tone-danger .gstat-icon { color: var(--danger); background: var(--danger-soft); }
.gstat.tone-danger strong { color: var(--danger); }
.gstat.tone-warning .gstat-icon { color: var(--warning); background: var(--warning-soft); }
.gstat.tone-warning strong { color: var(--warning); }
.gstat.tone-teal .gstat-icon { color: var(--teal); background: var(--teal-soft); }
.gstat.tone-accent .gstat-icon { color: var(--accent); background: var(--accent-soft); }
.gstat-plan {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 0 4px;
}

.gantt-panel { overflow: hidden; }
.gantt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.domain-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.domain-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.gantt-search { width: 210px; }
.gantt-search .input { min-height: 32px; padding-top: 5px; padding-bottom: 5px; font-size: 12px; }
.priority-tabs button { padding: 5px 9px; }
.view-tabs button { display: inline-flex; align-items: center; gap: 4px; }
.zoom { display: flex; gap: 4px; }

.inline-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  color: var(--danger);
  background: var(--danger-soft);
  font-size: 12px;
}
.inline-error .btn { margin-left: auto; }

.gantt-wrap { padding: 0 0 4px; }
.gantt-legend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.gantt-scroll {
  overflow: auto;
  max-height: clamp(380px, 60vh, 680px);
  background: var(--panel-inset);
  scrollbar-width: thin;
}
.gantt-inner { position: relative; }
.gantt-header {
  display: flex;
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--panel-solid);
  border-bottom: 1px solid var(--border-strong);
  min-height: 48px;
}
.rail-cell {
  flex: none;
  padding: 9px 12px;
  background: var(--panel-solid);
  border-right: 1px solid var(--border);
  position: sticky;
  left: 0;
  z-index: 4;
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
}
.corner {
  z-index: 7;
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: var(--text-3);
  gap: 1px;
  padding: 7px 12px;
}
.corner-sub { font-size: 10px; font-weight: 400; color: var(--text-3); }
.day-head { display: flex; flex: none; }
.day-cell {
  flex: none;
  padding: 6px 9px;
  border-right: 1px solid var(--border);
  display: flex;
  align-items: baseline;
  gap: 5px;
  color: var(--text-2);
  background: var(--panel-solid);
}
.day-cell.weekend { background: color-mix(in srgb, var(--panel-strong) 55%, transparent); }
.day-cell.today {
  background: var(--accent-soft);
  box-shadow: inset 0 -2px 0 var(--accent);
}
.day-num { font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--text); }
.day-sub { font-size: 10px; color: var(--text-3); }
.day-month { margin-left: auto; font-size: 10px; color: var(--text-3); }
.day-cell.today .day-month, .day-cell.today .day-sub { color: var(--accent); }

.gantt-row { display: flex; border-bottom: 1px solid var(--border); }
.gantt-row:last-child { border-bottom: none; }
.gantt-rows.loading { opacity: 0.55; transition: opacity 0.2s ease; }
.rail {
  border-bottom: 1px solid var(--border);
  gap: 2px;
  box-shadow: 6px 0 14px rgba(0, 0, 0, 0.08);
}
.rail.bottleneck { box-shadow: inset 3px 0 0 var(--danger), 6px 0 14px rgba(0, 0, 0, 0.08); }
.rail-top { display: flex; align-items: center; gap: 6px; flex: none; }
.rail-code { font-size: 10.5px; color: var(--text-3); }
.rail-name { font-size: 12px; font-weight: 600; color: var(--text); flex: none; }
.rail-meta { font-size: 10px; color: var(--text-3); flex: none; }
.track {
  position: relative;
  flex: none;
  background-image: linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-repeat: repeat-x;
  background-position: 0 0;
}
.freeze-band {
  position: absolute;
  top: 0;
  bottom: 0;
  background: repeating-linear-gradient(
    135deg,
    var(--accent-soft),
    var(--accent-soft) 6px,
    transparent 6px,
    transparent 12px
  );
  border-left: 1px dashed var(--accent-line);
  border-right: 1px dashed var(--accent-line);
  pointer-events: none;
  z-index: 1;
}
.now-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 0;
  border-left: 1px dashed var(--teal);
  opacity: 0.65;
  pointer-events: none;
  z-index: 2;
}
.baseline-tick {
  position: absolute;
  width: 2px;
  height: 18px;
  border-radius: 2px;
  background: var(--text-3);
  opacity: 0.65;
  z-index: 2;
}
.gantt-bar {
  position: absolute;
  height: 18px;
  border: 0;
  border-radius: 5px;
  padding: 0 5px;
  display: flex;
  align-items: center;
  gap: 4px;
  color: #08111f;
  font-size: 9.5px;
  font-weight: 650;
  line-height: 1;
  overflow: hidden;
  white-space: nowrap;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.22);
  z-index: 3;
  cursor: pointer;
  opacity: 0.94;
  transition: filter 0.15s ease, transform 0.15s ease;
  text-align: left;
}
.gantt-bar:hover { filter: brightness(1.12); transform: translateY(-1px); z-index: 4; }
.gantt-bar.tight { box-shadow: 0 0 0 1px var(--warning), 0 1px 5px rgba(0, 0, 0, 0.22); }
.gantt-bar.late { box-shadow: 0 0 0 1px var(--danger), 0 0 12px rgba(255, 99, 115, 0.4); }
.gantt-bar.locked {
  background-image: repeating-linear-gradient(135deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0.16) 3px, transparent 3px, transparent 7px);
}
.bar-text { overflow: hidden; text-overflow: ellipsis; }
.bar-lock { flex: none; display: inline-flex; }

.gantt-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 9px 16px;
  font-size: 10.5px;
  color: var(--text-3);
  border-top: 1px solid var(--border);
  background: var(--panel);
}

/* list */
.gantt-list .data-table tbody tr { cursor: pointer; }

/* drawer */
.drawer-title-block { display: flex; align-items: center; gap: 11px; min-width: 0; }
.drawer-domain { width: 4px; height: 34px; border-radius: 3px; flex: none; }
.drawer-title { font-size: 15px; font-weight: 700; }
.drawer-sub { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.detail-cell {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.detail-cell span { font-size: 10.5px; color: var(--text-3); }
.detail-cell strong { font-size: 12.5px; color: var(--text); font-weight: 600; }
.drawer-section { margin-top: 18px; }
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 650;
  color: var(--text-2);
  margin-bottom: 9px;
}
.reason-text {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
  padding: 11px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.baseline-diff {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--warning-soft);
  background: var(--warning-soft);
}
.baseline-diff.advanced { border-color: var(--success-soft); background: var(--success-soft); }
.bd-value { font-size: 22px; font-weight: 700; color: var(--warning); }
.baseline-diff.advanced .bd-value { color: var(--success); }
.bd-label { font-size: 12px; font-weight: 600; }

@media (max-width: 1279px) {
  .gstat-plan { margin-left: 0; width: 100%; }
  .gantt-toolbar { align-items: flex-start; }
  .toolbar-actions { width: 100%; }
  .gantt-search { flex: 1; min-width: 180px; }
}
@media (max-width: 767px) {
  .gantt-page { gap: 10px; }
  .plan-select { width: 100%; }
  .gantt-stats { gap: 8px; }
  .gstat { min-width: calc(33.33% - 6px); flex: 1; padding: 9px 10px; }
  .gstat strong { font-size: 16px; }
  .gstat-plan { padding: 0; }
  .gantt-toolbar { padding: 10px 12px; gap: 8px; }
  .domain-tabs { width: 100%; }
  .toolbar-actions { gap: 6px; }
  .gantt-search { width: 100%; flex-basis: 100%; }
  .view-tabs { margin-left: auto; }
  .gantt-scroll { max-height: 62vh; }
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
