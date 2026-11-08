<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { changesApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { Change, ChangeImpact } from '@/types'
import {
  CHANGE_TYPE_LABEL,
  PRIORITY_LABEL,
  SCENARIO_LABEL,
  SEVERITY_LABEL,
  formatDateTime,
  formatPercent,
  relativeTime,
  statusTone,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ClearanceBadge from '@/components/ClearanceBadge.vue'
import BaseModal from '@/components/BaseModal.vue'

interface Summary {
  total: number
  open: number
  critical: number
  counts: { status: string; count: number }[]
  types: { type: string; count: number }[]
  sla_minutes: number
  sla_target: string
  hidden_by_clearance?: number
  clearance_enabled?: boolean
}

const TYPE_OPTIONS = ['fault', 'material', 'insert', 'rework', 'order_change', 'inspection', 'ecn']
const SEVERITY_OPTIONS = ['warning', 'critical', 'fatal']

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const summary = ref<Summary | null>(null)
const list = ref<Change[]>([])
const loading = ref(false)
const listLoading = ref(false)
const error = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
const search = ref('')
const selectedId = ref<number | null>(null)
const detail = ref<Change | null>(null)
const detailLoading = ref(false)
const detailRef = ref<HTMLElement | null>(null)
const acting = ref(false)

const createOpen = ref(false)
const createForm = ref({
  type: 'fault',
  title: '',
  detail: '',
  severity: 'critical',
  delay_hours: 18,
  order_no: '',
})
const creating = ref(false)
const createError = ref('')

const resolveTarget = ref<Change | null>(null)
const resolving = ref(false)
const resolveError = ref('')

let searchTimer: number | null = null

const canCreate = computed(() => auth.can('changes:create'))
const canApprove = computed(() => auth.can('changes:approve'))
const openChanges = computed(() => list.value.filter((item) => item.status !== '已关闭'))
const hiddenChanges = computed(() => summary.value?.hidden_by_clearance ?? 0)

const statusOptions = computed(() => {
  const counts = summary.value?.counts || []
  return [{ status: '', count: summary.value?.total || 0 }, ...counts]
})

const graphGroups = computed(() => {
  const nodes = detail.value?.impact?.graph.nodes || []
  const labels = ['触发事件', '受影响订单', '工序域']
  return [0, 1, 2].map((level) => ({
    level,
    label: labels[level],
    nodes: nodes.filter((node) => node.level === level),
  }))
})

const sla = computed(() => {
  const impact = detail.value?.impact
  if (!impact) return null
  const elapsed = impact.summary.elapsed_minutes
  const target = impact.summary.sla_minutes || 15
  const ratio = Math.min(100, (elapsed / target) * 100)
  return {
    elapsed,
    display: elapsed < 1 ? `${Math.max(1, Math.round(elapsed * 60))} 秒` : `${elapsed.toFixed(1)} 分钟`,
    target,
    ratio,
    breached: elapsed > target,
    remaining: Math.max(0, target - elapsed),
  }
})

const showDelayField = computed(() => ['fault', 'material', 'rework'].includes(createForm.value.type))
const showOrderField = computed(() => ['insert', 'order_change', 'inspection'].includes(createForm.value.type))

async function loadSummary() {
  try {
    summary.value = await changesApi.summary()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const response = await changesApi.list({
      status: statusFilter.value || undefined,
      type: typeFilter.value || undefined,
      search: search.value.trim() || undefined,
      limit: 60,
    })
    list.value = response.items
    if (!selectedId.value && response.items.length) {
      const queryId = Number(route.query.change)
      const target = response.items.find((item) => item.id === queryId) || response.items[0]
      await selectChange(target.id, false)
    } else if (selectedId.value && !response.items.some((item) => item.id === selectedId.value)) {
      if (response.items.length) await selectChange(response.items[0].id, false)
      else {
        selectedId.value = null
        detail.value = null
      }
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    listLoading.value = false
  }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadSummary(), loadList()])
  } finally {
    loading.value = false
  }
}

async function selectChange(id: number, scroll = true) {
  selectedId.value = id
  detailLoading.value = true
  detail.value = list.value.find((item) => item.id === id) || null
  if (Number(route.query.change) !== id) router.replace({ query: { ...route.query, change: String(id) } })
  try {
    detail.value = await changesApi.detail(id)
  } catch (err) {
    ui.error('扰动详情加载失败', errorMessage(err))
  } finally {
    detailLoading.value = false
  }
  if (scroll && window.matchMedia('(max-width: 1023px)').matches) {
    window.setTimeout(() => detailRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
  }
}

function onSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => void loadList(), 320)
}

function setType(type: string) {
  typeFilter.value = typeFilter.value === type ? '' : type
  void loadList()
}

async function runAssess() {
  if (!detail.value || acting.value) return
  acting.value = true
  try {
    const updated = await changesApi.assess(detail.value.id)
    detail.value = updated
    ui.success('影响推演完成', updated.impact ? `影响 ${updated.impact.summary.affected_orders} 单 / ${updated.impact.summary.affected_operations} 道工序` : '已更新影响面')
    await Promise.all([loadSummary(), loadList()])
  } catch (err) {
    ui.error('推演失败', errorMessage(err))
  } finally {
    acting.value = false
  }
}

async function runPlans() {
  if (!detail.value || acting.value) return
  acting.value = true
  try {
    const result = await changesApi.plans(detail.value.id)
    detail.value = result.change
    ui.success('A/B 重排方案已生成', `${result.plans.length} 个候选方案已进入审批队列`)
    await Promise.all([loadSummary(), loadList()])
    const first = result.plans[0]
    if (first) {
      await router.push({ path: '/plans', query: { plan: first.id } })
    }
  } catch (err) {
    ui.error('方案生成失败', errorMessage(err))
  } finally {
    acting.value = false
  }
}

function openResolve(change: Change) {
  resolveTarget.value = change
  resolveError.value = ''
}

async function confirmResolve() {
  if (!resolveTarget.value) return
  resolving.value = true
  resolveError.value = ''
  try {
    const updated = await changesApi.resolve(resolveTarget.value.id)
    ui.success('扰动事件已关闭', updated.code)
    resolveTarget.value = null
    await Promise.all([loadSummary(), loadList()])
    if (detail.value?.id === updated.id) detail.value = updated
  } catch (err) {
    resolveError.value = errorMessage(err)
  } finally {
    resolving.value = false
  }
}

function openCreate() {
  createForm.value = {
    type: 'fault',
    title: '',
    detail: '',
    severity: 'critical',
    delay_hours: 18,
    order_no: '',
  }
  createError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  if (!createForm.value.title.trim()) {
    createError.value = '请填写扰动标题'
    return
  }
  if (!createForm.value.detail.trim()) {
    createError.value = '请描述扰动详情与影响范围'
    return
  }
  creating.value = true
  createError.value = ''
  const payload: Record<string, unknown> = {}
  if (showDelayField.value) payload.delay_hours = Number(createForm.value.delay_hours) || 0
  if (showOrderField.value && createForm.value.order_no.trim()) payload.order_no = createForm.value.order_no.trim()
  try {
    const created = await changesApi.create({
      type: createForm.value.type,
      title: createForm.value.title.trim(),
      detail: createForm.value.detail.trim(),
      severity: createForm.value.severity,
      payload,
    })
    createOpen.value = false
    ui.success('扰动事件已创建', '事件进入事件总线，15 分钟内完成影响推演')
    await loadAll()
    await selectChange(created.id)
  } catch (err) {
    createError.value = errorMessage(err)
  } finally {
    creating.value = false
  }
}

function planLink(planId: number) {
  router.push({ path: '/plans', query: { plan: planId } })
}

function gotoOrder(orderId: number) {
  router.push({ path: '/orders', query: { order: orderId } })
}

watch(
  () => route.query.change,
  (value) => {
    const id = Number(value)
    if (Number.isFinite(id) && id > 0 && id !== selectedId.value) void selectChange(id, false)
  },
)

onMounted(() => void loadAll())
onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="RIPPLE PROPAGATION · 协同执行"
      title="变更影响"
      subtitle="设备故障、物料缺料、紧急插单等扰动经图谱涟漪双向推演，量化交付影响并生成 A/B 协同重排方案。"
    >
      <template #actions>
        <button class="btn btn-sm" :disabled="loading" @click="loadAll">
          <span v-if="loading" class="spinner" /><AppIcon v-else name="refresh" :size="15" /> 刷新
        </button>
        <button v-if="canCreate" class="btn btn-sm btn-primary" @click="openCreate">
          <AppIcon name="plus" :size="15" /> 登记扰动
        </button>
      </template>
      <template #meta>
        <div class="flex items-center gap-10 fs-12 muted wrap">
          <span class="flex items-center gap-6"><span class="dot dot-live" />事件总线 RocketMQ 实时接入</span>
          <span class="hide-mobile">影响评估 SLA ≤ {{ summary?.sla_minutes || 15 }} 分钟</span>
        </div>
      </template>
    </PageHeader>

    <div v-if="error" class="panel inline-error"><AppIcon name="warning" :size="17" /> {{ error }}<button class="btn btn-sm" @click="loadAll">重试</button></div>

    <section class="change-summary">
      <div class="cs-card">
        <span class="cs-label">扰动总量</span>
        <strong class="num">{{ summary?.total || 0 }}</strong>
        <span class="cs-sub">未关闭 {{ summary?.open || 0 }}</span>
      </div>
      <div class="cs-card critical">
        <span class="cs-label">严重 / 致命</span>
        <strong class="num">{{ summary?.critical || 0 }}</strong>
        <span class="cs-sub">需优先处置</span>
      </div>
      <div class="cs-card">
        <span class="cs-label">评估 SLA</span>
        <strong class="num">{{ summary?.sla_minutes || 15 }}<em>min</em></strong>
        <span class="cs-sub">超时自动升级</span>
      </div>
      <div class="cs-types">
        <button
          v-for="item in summary?.types || []"
          :key="item.type"
          class="chip"
          :class="{ active: typeFilter === item.type }"
          @click="setType(item.type)"
        >
          {{ CHANGE_TYPE_LABEL[item.type] || item.type }}
          <span class="num">{{ item.count }}</span>
        </button>
      </div>
    </section>

    <div class="filter-bar">
      <div class="search-box change-search">
        <AppIcon name="search" :size="14" />
        <input v-model="search" class="input" placeholder="搜索事件编号 / 标题 / 详情" @input="onSearch" />
      </div>
      <select v-model="statusFilter" class="select status-select" @change="loadList">
        <option v-for="item in statusOptions" :key="item.status" :value="item.status">
          {{ item.status || '全部状态' }}{{ item.count ? `（${item.count}）` : '' }}
        </option>
      </select>
      <span class="fs-12 muted">点击事件查看涟漪推演</span>
    </div>

    <div class="change-layout">
      <section class="change-list panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />事件队列</div>
          <span class="panel-sub">
            {{ list.length }} 条
            <template v-if="hiddenChanges > 0"> · {{ hiddenChanges }} 条因密级未显示</template>
          </span>
        </div>
        <div class="change-scroll">
          <div v-if="listLoading && !list.length" class="skeleton" style="height: 220px; margin: 12px" />
          <div v-else-if="!list.length" class="empty">
            <span class="empty-icon"><AppIcon name="check" :size="20" /></span>
            暂无符合条件的扰动事件
          </div>
          <article
            v-for="change in list"
            :key="change.id"
            class="change-card"
            :class="{ active: selectedId === change.id }"
            @click="selectChange(change.id)"
          >
            <span class="cc-severity" :class="`sev-${change.severity}`" />
            <div class="cc-body">
              <div class="cc-top">
                <span class="badge" :class="change.severity === 'critical' || change.severity === 'fatal' ? 'badge-danger' : 'badge-warning'">
                  {{ SEVERITY_LABEL[change.severity] || change.severity }}
                </span>
                <span class="mono fs-12 muted">{{ change.code }}</span>
                <StatusBadge :status="change.status" :label="change.status" />
                <ClearanceBadge :level="change.clearance" />
              </div>
              <div class="cc-title">{{ change.title }}</div>
              <div class="cc-meta">
                <span>{{ CHANGE_TYPE_LABEL[change.type] || change.type }}</span>
                <span>{{ relativeTime(change.occurred_at) }}</span>
                <span v-if="change.impact">影响 {{ change.impact.summary.affected_orders }} 单</span>
                <span v-if="(change.redacted_affected || 0) > 0" class="text-warning">
                  {{ change.redacted_affected }} 单因密级隐去
                </span>
              </div>
              <div v-if="change.options?.plans?.length" class="cc-plans">
                <span class="badge badge-accent">{{ change.options.plans.length }} 个方案待审</span>
              </div>
            </div>
            <AppIcon name="chevronRight" :size="14" class="cc-arrow" />
          </article>
        </div>
      </section>

      <section ref="detailRef" class="change-detail">
        <div v-if="!detail" class="panel empty-detail">
          <span class="empty-icon"><AppIcon name="change" :size="24" /></span>
          <h3>选择扰動事件</h3>
          <p class="muted fs-13">查看图谱涟漪推演、受影响订单与候选重排方案。</p>
        </div>

        <template v-else>
          <div class="panel detail-hero">
            <div class="dh-top">
              <div class="dh-heading">
                <div class="dh-badges">
                  <span class="badge" :class="detail.severity === 'critical' || detail.severity === 'fatal' ? 'badge-danger' : 'badge-warning'">
                    {{ SEVERITY_LABEL[detail.severity] || detail.severity }}
                  </span>
                  <span class="mono fs-12 muted">{{ detail.code }}</span>
                  <StatusBadge :status="detail.status" :label="detail.status" />
                  <span class="badge badge-muted">{{ CHANGE_TYPE_LABEL[detail.type] || detail.type }}</span>
                </div>
                <h2>{{ detail.title }}</h2>
                <p class="dh-detail">{{ detail.detail }}</p>
                <div class="dh-meta">
                  <span><AppIcon name="user" :size="12" /> {{ detail.reporter }}</span>
                  <span><AppIcon name="clock" :size="12" /> {{ formatDateTime(detail.occurred_at) }}</span>
                  <span v-if="detail.resolved_at"><AppIcon name="check" :size="12" /> 关闭于 {{ formatDateTime(detail.resolved_at) }}</span>
                </div>
              </div>
              <div class="dh-actions">
                <button
                  v-if="canCreate && detail.status !== '已关闭'"
                  class="btn btn-sm"
                  :disabled="acting"
                  @click="runAssess"
                >
                  <span v-if="acting" class="spinner" /><AppIcon v-else name="zap" :size="13" />
                  {{ detail.impact ? '重新推演' : '影响推演' }}
                </button>
                <button
                  v-if="canCreate && detail.impact && detail.status !== '已关闭'"
                  class="btn btn-sm btn-primary"
                  :disabled="acting"
                  @click="runPlans"
                >
                  <AppIcon name="route" :size="13" /> 生成重排方案
                </button>
                <button v-if="canApprove && detail.status !== '已关闭'" class="btn btn-sm btn-danger" @click="openResolve(detail)">
                  关闭事件
                </button>
              </div>
            </div>

            <div v-if="sla && detail.status !== '已关闭'" class="sla-bar">
              <div class="sla-head">
                <span><AppIcon name="clock" :size="12" /> 评估耗时 {{ sla.display }} / SLA {{ sla.target }} 分钟</span>
                <span :class="sla.breached ? 'text-danger' : 'text-warning'">
                  {{ sla.breached ? '已超时，自动升级生产指挥部' : `剩余 ${sla.remaining.toFixed(1)} 分钟` }}
                </span>
              </div>
              <div class="progress"><i :style="{ width: `${sla.ratio}%`, background: sla.breached ? 'var(--danger)' : 'var(--accent)' }" /></div>
            </div>
          </div>

          <div v-if="detailLoading" class="panel detail-loading"><span class="spinner" /> 加载推演结果…</div>

          <template v-else-if="detail.impact">
            <section class="impact-grid">
              <div class="impact-card">
                <span>受影响订单</span>
                <strong class="num">{{ detail.impact.summary.affected_orders }}</strong>
                <em>{{ detail.impact.summary.critical_orders }} 个关键订单</em>
              </div>
              <div class="impact-card">
                <span>受影响工序</span>
                <strong class="num">{{ detail.impact.summary.affected_operations }}</strong>
                <em>{{ detail.impact.summary.domains.length }} 个工序域</em>
              </div>
              <div class="impact-card">
                <span>预计延误</span>
                <strong class="num text-warning">{{ detail.impact.summary.projected_delay_hours }}<small>h</small></strong>
                <em>最大逾期 {{ detail.impact.summary.max_late_days }} 天</em>
              </div>
              <div class="impact-card">
                <span>推演置信度</span>
                <strong class="num text-teal">{{ formatPercent(detail.impact.summary.confidence * 100, 0) }}</strong>
                <em>{{ detail.impact.summary.engine }}</em>
              </div>
            </section>

            <div v-if="detail.impact.summary.assumptions?.length" class="assumption-note">
              <AppIcon name="alert" :size="13" />
              <div>
                <strong>本次推演包含假设</strong>
                <ul>
                  <li v-for="item in detail.impact.summary.assumptions" :key="item">{{ item }}</li>
                </ul>
              </div>
            </div>

            <section class="panel ripple-panel">
              <div class="panel-head">
                <div class="panel-title"><span class="title-mark" />影响涟漪推演（依赖图实算）</div>
                <span class="panel-sub">{{ detail.impact.summary.resource }} · 按工序计划时间推算延误</span>
              </div>
              <div class="panel-body">
                <div class="ripple-flow">
                  <template v-for="(group, index) in graphGroups" :key="group.level">
                    <div class="ripple-col">
                      <div class="ripple-label">{{ group.label }}</div>
                      <div class="ripple-nodes">
                        <div
                          v-for="node in group.nodes.slice(0, 4)"
                          :key="node.id"
                          class="ripple-node"
                          :class="`rt-${node.type}`"
                        >
                          <span class="rn-dot" />
                          <div>
                            <strong>{{ node.label }}</strong>
                            <span v-if="node.type === 'event'">{{ node.meta.severity }} · {{ node.meta.type }}</span>
                            <span v-else-if="node.type === 'order'">{{ node.meta.priority }} · 逾期 {{ node.meta.late_days }} 天</span>
                            <span v-else>{{ node.meta.orders }} 单受影响</span>
                          </div>
                        </div>
                        <span v-if="group.nodes.length > 4" class="ripple-more">+{{ group.nodes.length - 4 }} 个节点</span>
                        <span v-if="!group.nodes.length" class="ripple-empty">—</span>
                      </div>
                    </div>
                    <div v-if="index < graphGroups.length - 1" class="ripple-arrow">
                      <AppIcon name="chevronRight" :size="18" />
                      <span class="ripple-edge">ripple</span>
                    </div>
                  </template>
                </div>

                <div class="timeline">
                  <div v-for="entry in detail.impact.timeline" :key="entry.time + entry.text" class="tl-item">
                    <span class="tl-time mono">{{ entry.time }}</span>
                    <span class="tl-dot" />
                    <span class="tl-text">{{ entry.text }}</span>
                  </div>
                </div>

                <div class="recommendation">
                  <AppIcon name="spark" :size="16" />
                  <p>{{ detail.impact.recommendation }}</p>
                </div>
              </div>
            </section>

            <section class="panel">
              <div class="panel-head">
                <div class="panel-title"><span class="title-mark" />受影响订单</div>
                <span class="panel-sub">
                  列出 {{ detail.impact.affected_orders.length }} / 共 {{ detail.impact.summary.affected_orders }} 单
                  <template v-if="(detail.impact.redacted_affected || 0) > 0">
                    · {{ detail.impact.redacted_affected }} 单因密级隐去
                  </template>
                </span>
              </div>
              <div class="panel-body flush">
                <div class="table-wrap">
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>订单</th>
                        <th>优先级</th>
                        <th>密级</th>
                        <th>交期</th>
                        <th>当前完工</th>
                        <th>预计完工</th>
                        <th>逾期</th>
                        <th>齐套</th>
                        <th>工序</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="order in detail.impact.affected_orders" :key="order.order_id" @click="gotoOrder(order.order_id)">
                        <td>
                          <div class="cell-strong mono">{{ order.order_no }}</div>
                          <div class="fs-12 muted truncate">{{ order.product_name }}</div>
                        </td>
                        <td><span class="priority" :class="`priority-${order.priority}`">{{ order.priority }}</span></td>
                        <td><ClearanceBadge :level="order.clearance" /></td>
                        <td>{{ formatDateTime(order.due_date) }}</td>
                        <td>{{ formatDateTime(order.current_finish) }}</td>
                        <td>{{ formatDateTime(order.projected_finish) }}</td>
                        <td>
                          <span class="badge" :class="order.late_days > 0 ? 'badge-danger' : 'badge-teal'">
                            {{ order.late_days > 0 ? `${order.late_days} 天` : '未逾期' }}
                          </span>
                        </td>
                        <td>{{ order.kit_status }}</td>
                        <td class="num">{{ order.operations }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section v-if="detail.options?.plans?.length" class="panel">
              <div class="panel-head">
                <div class="panel-title"><span class="title-mark" />候选重排方案</div>
                <router-link class="link" to="/plans">审批中心 <AppIcon name="chevrons" :size="12" /></router-link>
              </div>
              <div class="panel-body">
                <div class="option-grid">
                  <article v-for="plan in detail.options.plans" :key="plan.plan_id" class="option-card" @click="planLink(plan.plan_id)">
                    <div class="oc-head">
                      <span class="scenario-pill" :class="`scenario-${plan.scenario}`">{{ plan.scenario }}</span>
                      <div>
                        <strong>{{ SCENARIO_LABEL[plan.scenario] }}</strong>
                        <span class="mono">{{ plan.code }}</span>
                      </div>
                      <em class="num">{{ plan.score.toFixed(1) }}</em>
                    </div>
                    <div class="oc-kpis">
                      <div><span>准时率</span><strong class="num text-teal">{{ formatPercent(plan.on_time_rate, 1) }}</strong></div>
                      <div><span>逾期</span><strong class="num" :class="plan.late_orders ? 'text-danger' : 'text-success'">{{ plan.late_orders }}</strong></div>
                    </div>
                    <button class="btn btn-sm btn-ghost btn-block">查看方案并终审</button>
                  </article>
                </div>
              </div>
            </section>
          </template>

          <div v-else class="panel no-impact">
            <span class="empty-icon"><AppIcon name="zap" :size="22" /></span>
            <h3>{{ detail.status === '已关闭' ? '事件已关闭' : '尚未完成影响推演' }}</h3>
            <p class="muted fs-13">
              {{ detail.status === '已关闭' ? '关闭的事件保留完整影响面与方案记录，供审计追溯。' : '启动图谱涟漪推演，量化受影响订单、工序域与交付延误。' }}
            </p>
            <button v-if="canCreate && detail.status !== '已关闭'" class="btn btn-sm btn-primary" :disabled="acting" @click="runAssess">
              <span v-if="acting" class="spinner" /><AppIcon v-else name="zap" :size="13" /> 开始影响推演
            </button>
          </div>
        </template>
      </section>
    </div>

    <!-- Create modal -->
    <BaseModal v-model="createOpen" title="登记扰动事件" subtitle="事件进入 RocketMQ 事件总线，L0 门禁后启动涟漪推演" width="600px">
      <div class="create-form">
        <div class="create-grid">
          <label class="field">
            <span class="field-label">事件类型</span>
            <select v-model="createForm.type" class="select">
              <option v-for="type in TYPE_OPTIONS" :key="type" :value="type">{{ CHANGE_TYPE_LABEL[type] }}</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">严重等级</span>
            <select v-model="createForm.severity" class="select">
              <option v-for="severity in SEVERITY_OPTIONS" :key="severity" :value="severity">{{ SEVERITY_LABEL[severity] }}</option>
            </select>
          </label>
        </div>
        <label class="field">
          <span class="field-label">事件标题</span>
          <input v-model="createForm.title" class="input" placeholder="例如：五轴加工中心 DMC02 主轴故障停机" maxlength="80" />
        </label>
        <label class="field">
          <span class="field-label">详情与影响范围</span>
          <textarea v-model="createForm.detail" class="textarea" rows="3" placeholder="描述发生时间、设备/物料/订单、当前处置状态与已知影响" maxlength="600" />
        </label>
        <label v-if="showDelayField" class="field">
          <span class="field-label">预计延误（小时）</span>
          <input v-model.number="createForm.delay_hours" class="input" type="number" min="1" max="720" />
        </label>
        <label v-if="showOrderField" class="field">
          <span class="field-label">关联订单号（可选）</span>
          <input v-model="createForm.order_no" class="input" placeholder="MO-2026-XXXX" />
        </label>
        <div class="create-note">
          <AppIcon name="info" :size="14" />
          事件创建后 15 分钟内须完成影响评估，超时将自动升级生产指挥部。所有操作写入哈希审计链。
        </div>
        <div v-if="createError" class="create-error"><AppIcon name="warning" :size="14" /> {{ createError }}</div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" :disabled="creating" @click="createOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="creating" @click="submitCreate">
          <span v-if="creating" class="spinner" /><AppIcon v-else name="plus" :size="14" /> 登记事件
        </button>
      </template>
    </BaseModal>

    <!-- Resolve modal -->
    <BaseModal :model-value="Boolean(resolveTarget)" title="关闭扰动事件" subtitle="关闭后事件保留完整记录，不可再生成方案" width="440px" @update:model-value="resolveTarget = null">
      <div v-if="resolveTarget" class="resolve-body">
        <div class="resolve-icon"><AppIcon name="shield" :size="22" /></div>
        <p class="fs-13">
          确认关闭 <strong class="mono">{{ resolveTarget.code }}</strong>？
        </p>
        <p class="fs-12 muted">{{ resolveTarget.title }}</p>
        <div v-if="resolveError" class="create-error"><AppIcon name="warning" :size="14" /> {{ resolveError }}</div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" :disabled="resolving" @click="resolveTarget = null">取消</button>
        <button class="btn btn-danger" :disabled="resolving" @click="confirmResolve">
          <span v-if="resolving" class="spinner" /><AppIcon v-else name="check" :size="14" /> 确认关闭
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.inline-error { display: flex; align-items: center; gap: 9px; padding: 11px 15px; margin-bottom: 14px; color: var(--danger); }
.inline-error .btn { margin-left: auto; }

.change-summary {
  display: flex;
  gap: 10px;
  align-items: stretch;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.cs-card {
  min-width: 140px;
  padding: 12px 15px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cs-label { font-size: 10.5px; color: var(--text-3); }
.cs-card strong { font-size: 23px; line-height: 1.15; }
.cs-card strong em { font-style: normal; font-size: 11px; color: var(--text-3); margin-left: 2px; }
.cs-sub { font-size: 10px; color: var(--text-3); }
.cs-card.critical strong { color: var(--danger); }
.cs-types {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 0;
}
.cs-types .chip { height: 27px; font-size: 11px; }
.cs-types .chip span { color: var(--accent); }

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.change-search { width: 300px; }
.change-search .input { min-height: 34px; font-size: 12px; }
.status-select { width: 150px; min-height: 34px; font-size: 12px; }

.change-layout {
  display: grid;
  grid-template-columns: minmax(300px, 370px) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.change-list { overflow: hidden; }
.change-scroll { max-height: 1180px; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 7px; }
.change-card {
  display: flex;
  gap: 10px;
  padding: 11px 11px 11px 13px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  cursor: pointer;
  transition: border-color 0.16s ease, background-color 0.16s ease, transform 0.16s ease;
  position: relative;
}
.change-card:hover { border-color: var(--border-strong); }
.change-card.active { border-color: var(--accent-line); background: var(--accent-soft); }
.cc-severity {
  width: 3px;
  border-radius: 3px;
  background: var(--warning);
  flex: none;
}
.cc-severity.sev-critical, .cc-severity.sev-fatal { background: var(--danger); }
.cc-body { flex: 1; min-width: 0; }
.cc-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cc-top :deep(.badge) { height: 19px; font-size: 10px; }
.cc-title { font-size: 12.5px; font-weight: 650; margin-top: 5px; line-height: 1.4; }
.cc-meta { display: flex; flex-wrap: wrap; gap: 4px 9px; font-size: 10px; color: var(--text-3); margin-top: 3px; }
.cc-plans { margin-top: 6px; }
.cc-arrow { color: var(--text-3); flex: none; align-self: center; }

.change-detail { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.empty-detail, .no-impact {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  text-align: center;
}
.no-impact h3, .empty-detail h3 { font-size: 15px; }
.no-impact .btn { margin-top: 5px; }

.detail-hero { padding: 18px 20px; }
.dh-top { display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; }
.dh-heading { flex: 1; min-width: 240px; }
.dh-badges { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.dh-heading h2 { font-size: 19px; font-weight: 720; margin-top: 7px; line-height: 1.3; }
.dh-detail { font-size: 12px; color: var(--text-2); line-height: 1.65; margin-top: 5px; max-width: 720px; }
.dh-meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 10.5px; color: var(--text-3); margin-top: 8px; }
.dh-meta span { display: inline-flex; align-items: center; gap: 4px; }
.dh-actions { display: flex; flex-direction: column; gap: 7px; flex: none; }
.sla-bar { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--border); }
.sla-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; font-size: 10.5px; color: var(--text-3); margin-bottom: 6px; }
.sla-head span { display: inline-flex; align-items: center; gap: 4px; }

.detail-loading { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 40px; color: var(--text-3); font-size: 12px; }

.impact-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
}
.impact-card {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.impact-card > span { font-size: 10.5px; color: var(--text-3); }
.impact-card strong { font-size: 23px; line-height: 1.15; }
.impact-card strong small { font-size: 11px; color: var(--text-3); }
.impact-card em { font-style: normal; font-size: 9.5px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.assumption-note {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  margin: -4px 0 14px;
  padding: 10px 12px;
  border-radius: 9px;
  border: 1px dashed var(--border-strong);
  background: var(--panel-inset);
  font-size: 11px;
  color: var(--text-2);
}
.assumption-note :deep(svg) { flex: none; margin-top: 1px; color: var(--warning); }
.assumption-note strong { display: block; font-size: 11px; margin-bottom: 3px; color: var(--text-1); }
.assumption-note ul { margin: 0; padding-left: 16px; line-height: 1.6; color: var(--text-3); }

.ripple-panel .panel-body { display: flex; flex-direction: column; gap: 16px; }
.ripple-flow {
  display: flex;
  align-items: stretch;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.ripple-col { flex: 1; min-width: 150px; }
.ripple-label {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-3);
  text-transform: uppercase;
  margin-bottom: 7px;
}
.ripple-nodes { display: flex; flex-direction: column; gap: 5px; }
.ripple-node {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 8px 9px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.ripple-node strong { display: block; font-size: 10.5px; font-weight: 600; line-height: 1.35; }
.ripple-node span { display: block; font-size: 9px; color: var(--text-3); margin-top: 1px; }
.rn-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--warning); flex: none; margin-top: 4px; }
.rt-event { border-color: color-mix(in srgb, var(--danger) 35%, transparent); background: var(--danger-soft); }
.rt-event .rn-dot { background: var(--danger); }
.rt-order .rn-dot { background: var(--accent); }
.rt-domain .rn-dot { background: var(--teal); }
.ripple-more, .ripple-empty { font-size: 9px; color: var(--text-3); padding: 2px 0; }
.ripple-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--text-3);
  flex: none;
  width: 32px;
}
.ripple-edge { font-size: 8px; color: var(--text-3); font-family: var(--mono); }

.timeline { display: flex; flex-direction: column; gap: 0; padding-left: 4px; }
.tl-item { display: flex; align-items: flex-start; gap: 9px; position: relative; padding-bottom: 9px; }
.tl-item:last-child { padding-bottom: 0; }
.tl-time { font-size: 9.5px; color: var(--accent); flex: none; width: 44px; padding-top: 1px; }
.tl-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--panel-solid);
  border: 1.5px solid var(--accent);
  flex: none;
  margin-top: 3px;
  position: relative;
}
.tl-item:not(:last-child) .tl-dot::after {
  content: '';
  position: absolute;
  left: 2px;
  top: 9px;
  width: 1px;
  height: 18px;
  background: var(--border-strong);
}
.tl-text { font-size: 11px; color: var(--text-2); line-height: 1.5; }

.recommendation {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
.recommendation p { font-size: 11.5px; color: var(--text-2); line-height: 1.6; }

.data-table tbody tr { cursor: pointer; }

.option-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.option-card {
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  transition: border-color 0.16s ease;
}
.option-card:hover { border-color: var(--border-accent); }
.oc-head { display: flex; align-items: center; gap: 8px; }
.oc-head > div { flex: 1; min-width: 0; }
.oc-head strong { display: block; font-size: 11.5px; }
.oc-head span { font-size: 9.5px; color: var(--text-3); }
.oc-head > em { font-style: normal; font-size: 18px; font-weight: 700; color: var(--accent); }
.scenario-pill {
  width: 29px;
  height: 29px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  font-family: var(--mono);
  font-weight: 700;
  font-size: 12px;
  flex: none;
}
.scenario-A { color: var(--accent); background: var(--accent-soft); border: 1px solid var(--accent-line); }
.scenario-B { color: var(--blue); background: var(--blue-soft); border: 1px solid color-mix(in srgb, var(--blue) 30%, transparent); }
.oc-kpis { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.oc-kpis > div { display: flex; justify-content: space-between; padding: 6px 8px; border-radius: 6px; background: var(--panel-solid); font-size: 10px; color: var(--text-3); }
.oc-kpis strong { font-size: 11.5px; }
.link { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--accent); }

/* create */
.create-form { display: flex; flex-direction: column; gap: 12px; }
.create-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.create-note {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  padding: 9px 11px;
  border-radius: 7px;
  background: var(--panel-inset);
  border: 1px dashed var(--border-strong);
  font-size: 10px;
  color: var(--text-3);
  line-height: 1.5;
}
.create-note :deep(svg) { flex: none; margin-top: 1px; }
.create-error {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  padding: 9px 11px;
  border-radius: 7px;
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  color: var(--danger);
  font-size: 11.5px;
}
.resolve-body { display: flex; flex-direction: column; align-items: center; gap: 9px; text-align: center; padding: 8px 0; }
.resolve-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
}

@media (max-width: 1023px) {
  .change-layout { grid-template-columns: 1fr; }
  .change-scroll { max-height: 360px; }
  .impact-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .option-grid { grid-template-columns: 1fr; }
}
@media (max-width: 767px) {
  .change-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .cs-types { grid-column: span 2; justify-content: flex-start; }
  .change-search { width: 100%; }
  .status-select { flex: 1; }
  .filter-bar > .muted { display: none; }
  .dh-actions { width: 100%; flex-direction: row; flex-wrap: wrap; }
  .dh-actions .btn { flex: 1; }
  .ripple-arrow { width: 18px; }
  .impact-grid { gap: 7px; }
  .impact-card strong { font-size: 20px; }
  .ripple-flow { flex-direction: column; }
  .ripple-arrow { transform: rotate(90deg); height: 24px; justify-content: center; }
  .create-grid { grid-template-columns: 1fr; }
}
</style>
