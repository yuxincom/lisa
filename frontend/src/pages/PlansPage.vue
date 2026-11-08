<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { plansApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { PendingBatch, Plan } from '@/types'
import {
  SCENARIO_LABEL,
  SCENARIO_NOTE,
  formatDateTime,
  formatHours,
  formatNumber,
  formatPercent,
  relativeTime,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import RingGauge from '@/components/RingGauge.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

const WEIGHT_LABEL: Record<string, string> = {
  delivery: '交期',
  bottleneck: '瓶颈',
  changeover: '换型',
  cost: '成本',
}
const CHECK_GROUP_LABEL: Record<string, string> = {
  rule: '排产规则',
  hard: '硬约束',
  soft: '软约束',
}
const NODE_LABEL: Record<string, string> = {
  plan: '排产方案',
  dataset: '数据集',
  rule: '规则库',
  constraint: '约束',
  solver: '求解器',
  approval: '终审签名',
  baseline: '基线',
  disturbance: '扰动事件',
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const batches = ref<PendingBatch[]>([])
const plansList = ref<Plan[]>([])
const counts = ref<Record<string, number>>({})
const loading = ref(false)
const error = ref('')
const filter = ref('pending')

const detail = ref<Plan | null>(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const lineage = ref<{ nodes: { id: string; label: string; type: string; meta: Record<string, unknown> }[]; edges: { source: string; target: string; label: string }[]; prov: Record<string, unknown> } | null>(null)

const signTarget = ref<Plan | null>(null)
const signAction = ref<'approve' | 'reject'>('approve')
const password = ref('')
const comment = ref('')
const signing = ref(false)
const signError = ref('')
const feedbackSent = ref(false)

const pendingPlans = computed(() => batches.value.flatMap((batch) => batch.plans))
const pendingScore = computed(() => {
  if (!pendingPlans.value.length) return 0
  return pendingPlans.value.reduce((sum, plan) => sum + (plan.kpi?.total_score || 0), 0) / pendingPlans.value.length
})
const filteredPlans = computed(() => {
  if (filter.value === 'pending') return []
  const value = filter.value
  return plansList.value.filter((plan) => value === 'all' || plan.status === value)
})

const filters = computed(() => [
  { key: 'pending', label: '待审批', count: counts.value.pending || 0 },
  { key: 'applied', label: '已签发', count: counts.value.applied || 0 },
  { key: 'approved', label: '已审批', count: counts.value.approved || 0 },
  { key: 'rejected', label: '已驳回', count: counts.value.rejected || 0 },
  { key: 'superseded', label: '已择优', count: counts.value.superseded || 0 },
  { key: 'all', label: '全部', count: Object.values(counts.value).reduce((sum, value) => sum + value, 0) },
])

const detailWeights = computed(() => {
  const weights = detail.value?.weights || {}
  return Object.entries(weights).map(([key, value]) => ({
    key,
    label: WEIGHT_LABEL[key] || key,
    value: Math.round(Number(value) * 100),
  }))
})

const detailChecks = computed(() => detail.value?.summary?.hard_checks || [])
const detailSoft = computed(() => detail.value?.summary?.soft_violations || [])
const skippedChecks = computed(() => detailChecks.value.filter((check) => check.evaluated === false))
const failingChecks = computed(
  () => detailChecks.value.filter((check) => check.evaluated !== false && !check.passed).length,
)

const canApprove = computed(() => auth.can('plans:approve'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [batchResponse, planResponse] = await Promise.all([
      plansApi.pendingBatches(),
      plansApi.list({ limit: 60, include_history: false }),
    ])
    batches.value = batchResponse.items
    plansList.value = planResponse.items
    counts.value = planResponse.counts
    const queryId = Number(route.query.plan)
    if (Number.isFinite(queryId) && queryId > 0 && !detailOpen.value) {
      await openDetail(queryId)
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function openDetail(id: number) {
  detailLoading.value = true
  detailOpen.value = true
  feedbackSent.value = false
  lineage.value = null
  try {
    const [plan, flow] = await Promise.all([plansApi.detail(id), plansApi.lineage(id).catch(() => null)])
    detail.value = plan
    lineage.value = flow
    if (Number(route.query.plan) !== id) router.replace({ query: { ...route.query, plan: String(id) } })
  } catch (err) {
    ui.error('方案详情加载失败', errorMessage(err))
    detailOpen.value = false
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  const query = { ...route.query }
  delete query.plan
  router.replace({ query })
}

function startSign(plan: Plan, action: 'approve' | 'reject') {
  signTarget.value = plan
  signAction.value = action
  password.value = ''
  comment.value = action === 'approve' ? '同意签发，按方案执行' : ''
  signError.value = ''
}

async function submitSign() {
  if (!signTarget.value) return
  if (!password.value) {
    signError.value = '请输入当前账号密码完成电子签名'
    return
  }
  if (signAction.value === 'reject' && !comment.value.trim()) {
    signError.value = '驳回必须填写原因，便于人机分歧回流'
    return
  }
  signing.value = true
  signError.value = ''
  try {
    const result = await plansApi.approve(signTarget.value.id, {
      plan_id: signTarget.value.id,
      action: signAction.value,
      comment: comment.value.trim(),
      password: password.value,
    })
    const applied = result.apply?.operations_updated
    if (signAction.value === 'approve') {
      ui.success('方案已签发', applied ? `写保护网关已更新 ${applied} 道工序，基线切换完成` : '已写入 APS/MES')
    } else {
      ui.warning('方案已驳回', '已进入重排回路，扰动事件挂起')
    }
    signTarget.value = null
    detailOpen.value = false
    detail.value = null
    await load()
  } catch (err) {
    signError.value = errorMessage(err)
  } finally {
    signing.value = false
  }
}

async function sendFeedback(accepted: boolean) {
  if (!detail.value) return
  try {
    await plansApi.feedback(detail.value.id, accepted, accepted ? '认可当前方案' : '存在人机分歧，已提交复核')
    feedbackSent.value = true
    ui.success('反馈已采集', accepted ? '正向样本已回流影子数据集' : '分歧样本已回流影子数据集（R010）')
  } catch (err) {
    ui.error('反馈提交失败', errorMessage(err))
  }
}

function remaining(minutes?: number | null): string {
  if (minutes === undefined || minutes === null) return '—'
  if (minutes <= 0) return '已超时'
  return `${Math.max(1, Math.round(minutes))} 分钟`
}

function scoreTone(score: number): string {
  if (score >= 80) return 'var(--success)'
  if (score >= 60) return 'var(--accent)'
  return 'var(--warning)'
}

watch(filter, () => {
  if (filter.value !== 'pending' && !plansList.value.length) void load()
})

watch(
  () => route.query.plan,
  (value) => {
    const id = Number(value)
    if (Number.isFinite(id) && id > 0 && detail.value?.id !== id) void openDetail(id)
  },
)

onMounted(() => void load())
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="HUMAN-IN-THE-LOOP · 决策层"
      title="方案审批"
      subtitle="A/B/C 多目标候选方案同屏对比，白盒归因、硬约束校验、基线差异与 PROV-O 溯源全量呈现，电子签名后由写保护网关签发。"
    >
      <template #actions>
        <button class="btn btn-sm" :disabled="loading" @click="load">
          <span v-if="loading" class="spinner" /><AppIcon v-else name="refresh" :size="15" /> 刷新
        </button>
        <router-link class="btn btn-sm btn-teal" to="/gantt">
          <AppIcon name="gantt" :size="15" /> 查看甘特
        </router-link>
      </template>
      <template #meta>
        <div class="flex items-center gap-10 fs-12 muted wrap">
          <span class="flex items-center gap-6"><span class="dot dot-live" />审批超时 15 分钟自动升级生产指挥部</span>
          <span class="hide-mobile">写保护网关 · LLM/求解器禁写</span>
        </div>
      </template>
    </PageHeader>

    <div v-if="error" class="panel page-error">
      <AppIcon name="warning" :size="18" /> {{ error }}
      <button class="btn btn-sm" @click="load">重试</button>
    </div>

    <section class="review-stats">
      <div class="review-stat">
        <span class="rs-label">待审批批次</span>
        <strong class="num">{{ batches.length }}</strong>
        <span class="rs-sub">{{ pendingPlans.length }} 个候选方案</span>
      </div>
      <div class="review-stat">
        <span class="rs-label">待批工序</span>
        <strong class="num">{{ formatNumber(pendingPlans.reduce((sum, plan) => sum + (plan.summary?.operations || 0), 0)) }}</strong>
        <span class="rs-sub">A/B/C 方案合计</span>
      </div>
      <div class="review-stat">
        <span class="rs-label">P0 军品订单</span>
        <strong class="num text-accent">{{ formatNumber(pendingPlans.reduce((sum, plan) => sum + (plan.summary?.p0_orders || 0), 0)) }}</strong>
        <span class="rs-sub">ε 约束锁定交期</span>
      </div>
      <div class="review-stat">
        <span class="rs-label">平均候选评分</span>
        <strong class="num" :style="{ color: scoreTone(pendingScore) }">{{ pendingScore.toFixed(1) }}</strong>
        <span class="rs-sub">加权多目标终选</span>
      </div>
      <div class="review-stat">
        <span class="rs-label">生效基线</span>
        <strong class="num">{{ formatNumber(counts.applied || 0) }}</strong>
        <span class="rs-sub">已签发方案</span>
      </div>
    </section>

    <div class="filter-bar">
      <div class="segmented">
        <button
          v-for="item in filters"
          :key="item.key"
          :class="{ active: filter === item.key }"
          @click="filter = item.key"
        >
          {{ item.label }}
          <span v-if="item.count" class="seg-count">{{ item.count }}</span>
        </button>
      </div>
      <div class="filter-hint">
        <AppIcon name="shield" :size="14" />
        写保护网关 · 未审批方案禁止写入 APS/MES
      </div>
    </div>

    <!-- Pending batches -->
    <template v-if="filter === 'pending'">
      <div v-if="loading && !batches.length" class="batch-grid">
        <div v-for="n in 2" :key="n" class="skeleton" style="height: 340px; border-radius: 14px" />
      </div>
      <div v-else-if="!batches.length" class="panel empty-block">
        <span class="empty-icon"><AppIcon name="check" :size="24" /></span>
        <h3>审批队列已清空</h3>
        <p class="muted fs-13">所有候选方案均已完成终审，生产基线保持稳定。</p>
        <router-link class="btn btn-sm" to="/gantt">查看当前基线</router-link>
      </div>

      <div v-else class="batch-stack">
        <section v-for="batch in batches" :key="batch.batch_id" class="panel batch">
          <header class="batch-head">
            <div class="batch-heading">
              <div class="batch-eyebrow">
                <AppIcon name="approval" :size="13" />
                终审批次 · {{ batch.type === 'change' ? '扰动协同重排' : '常规重排' }}
              </div>
              <div class="batch-title">
                批次 {{ batch.batch_id }}
                <span v-if="batch.change_id" class="badge badge-warning">扰动 #{{ batch.change_id }}</span>
                <span class="badge badge-accent">推荐 {{ SCENARIO_LABEL[batch.recommended] || batch.recommended }}</span>
              </div>
              <div class="batch-meta">
                <span>提交于 {{ formatDateTime(batch.created_at) }}</span>
                <span>{{ relativeTime(batch.created_at) }}</span>
                <span>{{ batch.plans.length }} 个候选方案</span>
              </div>
            </div>
            <div class="batch-timer" :class="{ urgent: (batch.plans[0]?.approval?.minutes_left ?? 99) <= 5 }">
              <span class="bt-label">审批剩余</span>
              <strong class="num">{{ remaining(batch.plans[0]?.approval?.minutes_left) }}</strong>
              <span class="bt-sub">{{ batch.plans[0]?.approval?.escalated ? '已升级指挥部' : '超时自动升级' }}</span>
            </div>
          </header>

          <div class="scenario-grid">
            <article
              v-for="plan in batch.plans"
              :key="plan.id"
              class="scenario-card"
              :class="{ recommended: plan.scenario === batch.recommended }"
            >
              <div class="sc-head">
                <span class="sc-letter" :class="`sc-${plan.scenario}`">{{ plan.scenario }}</span>
                <div class="sc-title">
                  <strong>{{ SCENARIO_LABEL[plan.scenario] || plan.objective }}</strong>
                  <span>{{ SCENARIO_NOTE[plan.scenario] }}</span>
                </div>
                <span v-if="plan.scenario === batch.recommended" class="badge badge-accent">推荐</span>
              </div>

              <div class="sc-score">
                <RingGauge :value="plan.kpi?.total_score || 0" :size="82" :stroke="7" :color="scoreTone(plan.kpi?.total_score || 0)" suffix="" />
                <div class="sc-score-meta">
                  <div><span>加权总分</span><strong class="num">{{ (plan.kpi?.total_score || 0).toFixed(1) }}</strong></div>
                  <div><span>准时率</span><strong class="num text-teal">{{ formatPercent(plan.kpi?.on_time_rate, 1) }}</strong></div>
                  <div><span>逾期</span><strong class="num" :class="plan.kpi?.late_orders ? 'text-danger' : 'text-success'">{{ plan.kpi?.late_orders || 0 }}</strong></div>
                </div>
              </div>

              <div class="sc-kpis">
                <div><span>移动作业</span><strong>{{ plan.diff?.moved ?? 0 }}</strong></div>
                <div><span>冻结锁定</span><strong>{{ plan.kpi?.locked_operations ?? 0 }}</strong></div>
                <div><span>换型</span><strong>{{ formatHours(plan.kpi?.changeover_minutes) }}</strong></div>
                <div><span>Makespan</span><strong>{{ (plan.kpi?.makespan_hours || 0).toFixed(1) }}h</strong></div>
              </div>

              <div class="sc-weights">
                <div v-for="(weight, key) in plan.weights" :key="key" class="weight-line">
                  <span>{{ WEIGHT_LABEL[key] || key }}</span>
                  <div class="weight-track"><i :style="{ width: `${Math.round(Number(weight) * 100)}%` }" /></div>
                  <em class="num">{{ Math.round(Number(weight) * 100) }}%</em>
                </div>
              </div>

              <div class="sc-flags">
                <span class="badge" :class="plan.summary?.soft_violations?.length ? 'badge-warning' : 'badge-success'">
                  <span class="dot" />{{ plan.summary?.soft_violations?.length || 0 }} 软约束偏离
                </span>
                <span class="badge badge-blue"><span class="dot" />14 项硬约束通过</span>
              </div>

              <div class="sc-actions">
                <button class="btn btn-sm btn-ghost" @click="openDetail(plan.id)">白盒详情</button>
                <button
                  v-if="canApprove && plan.status === 'pending'"
                  class="btn btn-sm btn-primary grow"
                  @click="startSign(plan, 'approve')"
                >
                  <AppIcon name="signature" :size="13" /> 终审签发
                </button>
                <button
                  v-else-if="canApprove"
                  class="btn btn-sm grow"
                  @click="startSign(plan, 'reject')"
                >
                  驳回
                </button>
                <span v-else class="badge badge-muted">需审批权限</span>
              </div>
            </article>
          </div>
        </section>
      </div>
    </template>

    <!-- All plans table -->
    <section v-else class="panel">
      <div class="panel-head">
        <div class="panel-title"><span class="title-mark" />方案台账</div>
        <span class="panel-sub">{{ filteredPlans.length }} 条记录 · 不含历史归档</span>
      </div>
      <div class="panel-body flush">
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>方案</th>
                <th>场景</th>
                <th>状态</th>
                <th>准时率</th>
                <th>评分</th>
                <th>工序</th>
                <th>移动作业</th>
                <th>创建人</th>
                <th>创建时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="plan in filteredPlans" :key="plan.id" @click="openDetail(plan.id)">
                <td>
                  <div class="cell-strong mono">{{ plan.code }}</div>
                  <div class="fs-12 muted truncate">{{ plan.name }}</div>
                </td>
                <td><span class="badge badge-muted">{{ SCENARIO_LABEL[plan.scenario] || plan.scenario }}</span></td>
                <td><StatusBadge :status="plan.status" :label="plan.status_label" /></td>
                <td class="num text-teal">{{ formatPercent(plan.kpi?.on_time_rate, 1) }}</td>
                <td class="num">{{ (plan.kpi?.total_score || 0).toFixed(1) }}</td>
                <td class="num">{{ formatNumber(plan.kpi?.operations) }}</td>
                <td class="num">{{ plan.diff?.moved ?? 0 }}</td>
                <td>{{ plan.created_by }}</td>
                <td>{{ formatDateTime(plan.created_at) }}</td>
                <td class="cell-actions">
                  <button class="btn btn-sm" @click.stop="openDetail(plan.id)">详情</button>
                </td>
              </tr>
              <tr v-if="!filteredPlans.length">
                <td colspan="10"><div class="empty">暂无该状态的方案</div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Detail drawer -->
    <BaseDrawer v-model="detailOpen" width="1080px" @update:model-value="!$event && closeDetail()">
      <template #header>
        <div v-if="detail" class="detail-head">
          <div>
            <div class="detail-eyebrow">
              {{ detail.batch_id ? `批次 ${detail.batch_id}` : '单方案' }}
              <span v-if="detail.change" class="badge badge-warning">{{ detail.change.title }}</span>
            </div>
            <h3 class="detail-title">{{ detail.name }}</h3>
            <div class="detail-meta">
              <span class="mono">{{ detail.code }}</span>
              <StatusBadge :status="detail.status" :label="detail.status_label" />
              <span class="badge badge-muted">{{ SCENARIO_LABEL[detail.scenario] || detail.scenario }}</span>
              <span>{{ detail.created_by }} · {{ formatDateTime(detail.created_at) }}</span>
            </div>
          </div>
          <div class="detail-score">
            <RingGauge :value="detail.kpi?.total_score || 0" :size="76" :stroke="6" :color="scoreTone(detail.kpi?.total_score || 0)" suffix="" />
            <div>
              <span>加权总分</span>
              <strong class="num">{{ (detail.kpi?.total_score || 0).toFixed(1) }}</strong>
            </div>
          </div>
        </div>
      </template>

      <div v-if="detailLoading" class="detail-loading">
        <span class="spinner" /> 正在拉取白盒归因与溯源链…
      </div>

      <template v-else-if="detail">
        <div class="sibling-strip">
          <button
            class="chip"
            :class="{ active: true }"
            disabled
          >{{ detail.scenario }} · 当前</button>
          <button
            v-for="sibling in detail.siblings || []"
            :key="sibling.id"
            class="chip"
            @click="openDetail(sibling.id)"
          >
            {{ sibling.scenario }} · {{ sibling.status }} · {{ sibling.score?.toFixed(1) }}
          </button>
          <div class="sibling-spacer" />
          <router-link v-if="detail.change" class="link" :to="{ path: '/changes', query: { change: detail.change_id ?? undefined } }">
            查看扰动链路 <AppIcon name="external" :size="12" />
          </router-link>
          <router-link v-if="detail.status === 'applied' || detail.status === 'approved'" class="link" :to="{ path: '/gantt', query: { plan: detail.id } }">
            打开甘特 <AppIcon name="external" :size="12" />
          </router-link>
        </div>

        <div class="detail-kpis">
          <div class="dk"><span>准时交付率</span><strong class="num text-teal">{{ formatPercent(detail.kpi?.on_time_rate, 1) }}</strong></div>
          <div class="dk"><span>逾期订单</span><strong class="num" :class="detail.kpi?.late_orders ? 'text-danger' : 'text-success'">{{ detail.kpi?.late_orders ?? 0 }}</strong></div>
          <div class="dk"><span>平均利用率</span><strong class="num">{{ formatPercent(detail.kpi?.avg_utilization, 1) }}</strong></div>
          <div class="dk"><span>瓶颈利用率</span><strong class="num">{{ formatPercent(detail.kpi?.bottleneck_utilization, 1) }}</strong></div>
          <div class="dk"><span>换型时间</span><strong class="num">{{ formatHours(detail.kpi?.changeover_minutes) }}</strong></div>
          <div class="dk"><span>换型次数</span><strong class="num">{{ detail.kpi?.changeover_count ?? 0 }}</strong></div>
          <div class="dk"><span>冻结锁定</span><strong class="num">{{ detail.kpi?.locked_operations ?? 0 }}</strong></div>
          <div class="dk"><span>总工时</span><strong class="num">{{ formatNumber(detail.kpi?.total_labor_hours, 1) }}h</strong></div>
        </div>

        <div class="detail-columns">
          <div class="detail-col">
            <div class="drawer-section">
              <div class="section-title"><AppIcon name="spark" :size="14" /> 求解归因</div>
              <ol class="reason-list">
                <li v-for="(reason, index) in detail.summary?.reasoning || []" :key="index">
                  <span class="reason-no">{{ String(index + 1).padStart(2, '0') }}</span>
                  <span>{{ reason }}</span>
                </li>
              </ol>
              <div class="solver-meta">
                <div><span>求解器</span><strong>{{ detail.summary?.solver || 'LISA Heuristic Engine（贪心派工，无外部求解器）' }}</strong></div>
                <div><span>算法</span><strong>{{ detail.summary?.algorithm || 'ε约束 + 字典序修复' }}</strong></div>
                <div><span>生成智能体</span><strong>{{ detail.summary?.generated_by || 'C-01 全厂总控' }}</strong></div>
              </div>
            </div>

            <div class="drawer-section">
              <div class="section-title">
                <AppIcon name="check" :size="14" /> 硬约束校验
                <span class="badge" :class="failingChecks ? 'badge-danger' : 'badge-success'">
                  {{
                    failingChecks
                      ? `${failingChecks} 项失败`
                      : `${detailChecks.length - skippedChecks.length} 项全部通过`
                  }}
                </span>
                <span v-if="skippedChecks.length" class="badge badge-muted">
                  {{ skippedChecks.length }} 项未校验
                </span>
              </div>
              <div class="check-grid">
                <div
                  v-for="check in detailChecks"
                  :key="check.code"
                  class="check-cell"
                  :class="{ failed: check.evaluated !== false && !check.passed, skipped: check.evaluated === false }"
                  :title="check.evaluated === false ? check.message : check.description || check.message"
                >
                  <span class="check-code mono">{{ check.code }}</span>
                  <span class="check-title">{{ check.title }}</span>
                  <AppIcon
                    :name="check.evaluated === false ? 'info' : check.passed ? 'check' : 'x'"
                    :size="13"
                    class="check-icon"
                  />
                </div>
              </div>
              <p v-if="skippedChecks.length" class="fs-12 muted check-note">
                {{ skippedChecks.map((check) => `${check.code} ${check.title}：${check.message}`).join('；') }}
              </p>
            </div>

            <div v-if="detailSoft.length" class="drawer-section">
              <div class="section-title"><AppIcon name="warning" :size="14" /> 软约束偏离</div>
              <div v-for="soft in detailSoft" :key="soft.code" class="soft-item">
                <div class="soft-head">
                  <span class="mono">{{ soft.code }}</span>
                  <strong>{{ soft.title }}</strong>
                  <span class="badge badge-warning">{{ soft.count }}</span>
                </div>
                <p>{{ soft.message }}</p>
                <div v-if="soft.samples?.length" class="soft-samples">
                  <span v-for="sample in soft.samples" :key="sample" class="chip">{{ sample }}</span>
                </div>
              </div>
            </div>

            <div class="drawer-section">
              <div class="section-title"><AppIcon name="activity" :size="14" /> 相对基线差异</div>
              <div class="diff-summary">
                <div><span>移动</span><strong class="num">{{ detail.diff?.moved ?? 0 }}</strong></div>
                <div><span>新增</span><strong class="num">{{ detail.diff?.added ?? 0 }}</strong></div>
                <div><span>不变</span><strong class="num">{{ detail.diff?.unchanged ?? 0 }}</strong></div>
                <div><span>合计</span><strong class="num">{{ detail.diff?.total ?? 0 }}</strong></div>
              </div>
              <div class="table-wrap diff-table">
                <table class="data-table">
                  <thead>
                    <tr><th>订单 / 工序</th><th>域</th><th>原开始</th><th>新开始</th><th>偏差</th><th>资源</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="sample in detail.diff?.samples || []" :key="sample.operation_id">
                      <td>
                        <div class="cell-strong mono">{{ sample.order_no }}</div>
                        <div class="fs-12 muted">{{ sample.seq }} · {{ sample.name }}</div>
                      </td>
                      <td>{{ sample.domain }}</td>
                      <td>{{ formatDateTime(sample.from_start) }}</td>
                      <td>{{ formatDateTime(sample.to_start) }}</td>
                      <td>
                        <span class="badge" :class="sample.delta_hours < 0 ? 'badge-success' : 'badge-warning'">
                          {{ sample.delta_hours > 0 ? '+' : '' }}{{ sample.delta_hours.toFixed(1) }}h
                        </span>
                      </td>
                      <td>
                        <span v-if="sample.resource_changed" class="badge badge-blue">换机</span>
                        <span v-else class="muted">保持</span>
                      </td>
                    </tr>
                    <tr v-if="!detail.diff?.samples?.length">
                      <td colspan="6"><div class="empty">与基线无差异</div></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div class="detail-col">
            <div class="drawer-section">
              <div class="section-title"><AppIcon name="target" :size="14" /> 目标权重</div>
              <div class="weights-block">
                <div v-for="weight in detailWeights" :key="weight.key" class="weight-line big">
                  <span>{{ weight.label }}</span>
                  <div class="weight-track"><i :style="{ width: `${weight.value}%` }" /></div>
                  <em class="num">{{ weight.value }}%</em>
                </div>
              </div>
            </div>

            <div class="drawer-section">
              <div class="section-title"><AppIcon name="shield" :size="14" /> 审批与签名</div>
              <div v-if="detail.approval" class="approval-card">
                <div class="approval-top">
                  <StatusBadge :status="detail.approval.status === 'pending' ? 'pending' : detail.approval.status" :label="detail.approval.status === 'pending' ? '待终审' : detail.approval.status === 'approved' ? '已签署' : detail.approval.status" />
                  <span v-if="detail.approval.status === 'pending'" class="badge" :class="(detail.approval.minutes_left ?? 99) <= 5 ? 'badge-danger' : 'badge-warning'">
                    <AppIcon name="clock" :size="11" /> 剩余 {{ remaining(detail.approval.minutes_left) }}
                  </span>
                </div>
                <div class="kv"><span class="k">审批人</span><span class="v">{{ detail.approval.approver_name || '待指定' }}</span></div>
                <div class="kv"><span class="k">审批截止</span><span class="v">{{ formatDateTime(detail.approval.deadline) }}</span></div>
                <div class="kv"><span class="k">电子签名</span><span class="v hash">{{ detail.approval.signature || '尚未签署' }}</span></div>
                <div v-if="detail.approval.comment" class="approval-comment">{{ detail.approval.comment }}</div>
              </div>

              <div v-if="canApprove && detail.status === 'pending'" class="approval-actions">
                <button class="btn btn-primary btn-block" @click="detail && startSign(detail, 'approve')">
                  <AppIcon name="signature" :size="15" /> 电子签名 · 签发基线
                </button>
                <button class="btn btn-danger btn-block" @click="detail && startSign(detail, 'reject')">驳回并进入重排</button>
              </div>
              <div v-else-if="detail.status === 'applied'" class="applied-note">
                <AppIcon name="shield" :size="15" />
                方案已通过写保护网关写入 APS/MES，当前为生效基线。
              </div>
            </div>

            <div class="drawer-section">
              <div class="section-title"><AppIcon name="link" :size="14" /> PROV-O 溯源</div>
              <div v-if="lineage" class="prov-flow">
                <div v-for="node in lineage.nodes" :key="node.id" class="prov-node" :class="`type-${node.type}`">
                  <span class="prov-type">{{ NODE_LABEL[node.type] || node.type }}</span>
                  <strong>{{ node.label }}</strong>
                </div>
              </div>
              <div v-else class="fs-12 muted">溯源链加载中…</div>
              <div v-if="lineage" class="prov-foot">
                <span>{{ lineage.prov.bundle }}</span>
                <span>{{ lineage.prov.hard_checks }} 硬约束 · {{ lineage.prov.soft_violations }} 软约束</span>
                <span class="mono">trace {{ lineage.prov.trace_version }}</span>
              </div>
            </div>

            <div class="drawer-section">
              <div class="section-title"><AppIcon name="send" :size="14" /> 人机分歧采集</div>
              <p class="fs-12 muted" style="margin-bottom: 8px">采纳或否决将回流影子数据集，用于采纳率与准确率指标。</p>
              <div class="feedback-actions">
                <button class="btn btn-sm btn-teal" :disabled="feedbackSent" @click="sendFeedback(true)">认可方案</button>
                <button class="btn btn-sm" :disabled="feedbackSent" @click="sendFeedback(false)">存在分歧</button>
              </div>
              <div v-if="feedbackSent" class="fs-12 text-success" style="margin-top: 8px">已采集，等待回流。</div>
            </div>

            <div class="drawer-section">
              <div class="section-title"><AppIcon name="layers" :size="14" /> 覆盖范围</div>
              <div class="domain-counts">
                <span v-for="domain in detail.summary?.domains || []" :key="domain.name" class="chip">
                  {{ domain.name }} <em class="num">{{ domain.count }}</em>
                </span>
              </div>
              <div class="kv"><span class="k">订单 / 工序</span><span class="v">{{ detail.summary?.orders }} / {{ detail.summary?.operations }}</span></div>
              <div class="kv"><span class="k">涉及资源</span><span class="v">{{ detail.summary?.resources }}</span></div>
              <div class="kv"><span class="k">齐套风险</span><span class="v" :class="detail.summary?.kit_risk ? 'text-warning' : ''">{{ detail.summary?.kit_risk }} 单</span></div>
            </div>
          </div>
        </div>
      </template>

      <template #footer>
        <button class="btn btn-ghost" @click="closeDetail">关闭</button>
        <template v-if="detail">
          <button v-if="detail.status === 'pending' && canApprove" class="btn btn-danger" @click="startSign(detail, 'reject')">驳回</button>
          <router-link v-if="detail.status === 'applied'" class="btn btn-teal" :to="{ path: '/gantt', query: { plan: detail.id } }">打开甘特</router-link>
          <button v-if="detail.status === 'pending' && canApprove" class="btn btn-primary" @click="startSign(detail, 'approve')">
            <AppIcon name="signature" :size="15" /> 电子签名签发
          </button>
        </template>
      </template>
    </BaseDrawer>

    <!-- Signature modal -->
    <BaseModal
      :model-value="Boolean(signTarget)"
      :title="signAction === 'approve' ? '电子签名 · 终审签发' : '驳回方案'"
      :subtitle="signTarget?.code"
      width="480px"
      @update:model-value="signTarget = null"
    >
      <div v-if="signTarget" class="sign-body">
        <div class="sign-summary">
          <div class="sign-row"><span>方案</span><strong>{{ signTarget.name }}</strong></div>
          <div class="sign-row"><span>场景</span><span class="badge badge-muted">{{ SCENARIO_LABEL[signTarget.scenario] }}</span></div>
          <div class="sign-row"><span>作业</span><strong class="num">{{ signTarget.kpi?.operations }} 工序 / 移动 {{ signTarget.diff?.moved }} 道</strong></div>
          <div class="sign-row"><span>准时率</span><strong class="num text-teal">{{ formatPercent(signTarget.kpi?.on_time_rate, 1) }}</strong></div>
        </div>

        <div class="sign-shield">
          <AppIcon name="shield" :size="16" />
          <p>{{ signAction === 'approve' ? '签名后由写保护网关原子写入 APS/MES 并切换生效基线，操作不可逆。' : '驳回后方案进入重排回路，扰动事件将被挂起。' }}</p>
        </div>

        <label class="field">
          <span class="field-label">{{ signAction === 'approve' ? '审批意见' : '驳回原因（必填）' }}</span>
          <textarea v-model="comment" class="textarea" rows="3" :placeholder="signAction === 'approve' ? '同意签发，按方案执行' : '请说明驳回原因，便于人机分歧回流入影子数据集'" />
        </label>

        <label class="field">
          <span class="field-label">账号密码 · 电子签名校验</span>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="输入当前账号密码"
            autocomplete="current-password"
            @keydown.enter="submitSign"
          />
        </label>

        <div class="sign-meta">
          <span><AppIcon name="lock" :size="12" /> SHA-256 签名摘要</span>
          <span>签名人 {{ auth.displayName }} · {{ auth.roleLabel }}</span>
        </div>

        <div v-if="signError" class="sign-error"><AppIcon name="warning" :size="14" /> {{ signError }}</div>
      </div>

      <template #footer>
        <button class="btn btn-ghost" :disabled="signing" @click="signTarget = null">取消</button>
        <button
          class="btn"
          :class="signAction === 'approve' ? 'btn-primary' : 'btn-danger'"
          :disabled="signing"
          @click="submitSign"
        >
          <span v-if="signing" class="spinner" />
          <AppIcon v-else name="signature" :size="15" />
          {{ signAction === 'approve' ? '确认签名并签发' : '确认驳回' }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.page-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  margin-bottom: 14px;
  color: var(--danger);
}
.page-error .btn { margin-left: auto; }

.review-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.review-stat {
  padding: 13px 15px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.rs-label { font-size: 11px; color: var(--text-3); }
.review-stat strong { font-size: 24px; line-height: 1.15; font-weight: 700; }
.rs-sub { font-size: 10.5px; color: var(--text-3); }

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.seg-count {
  display: inline-grid;
  place-items: center;
  min-width: 17px;
  height: 16px;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 99px;
  background: var(--panel-inset);
  font-size: 9.5px;
  color: var(--text-3);
}
.segmented button.active .seg-count { background: var(--accent-soft); color: var(--accent); }
.filter-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
}

.batch-stack { display: flex; flex-direction: column; gap: 16px; }
.batch { overflow: hidden; }
.batch-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 17px 20px;
  border-bottom: 1px solid var(--border);
  background:
    radial-gradient(600px 160px at 0% 0%, var(--accent-soft), transparent 60%),
    transparent;
  flex-wrap: wrap;
}
.batch-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 700;
}
.batch-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 16px;
  font-weight: 700;
  margin-top: 5px;
}
.batch-meta { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--text-3); margin-top: 5px; }
.batch-timer {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  padding: 9px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  flex: none;
}
.batch-timer.urgent { border-color: color-mix(in srgb, var(--danger) 45%, transparent); background: var(--danger-soft); }
.bt-label { font-size: 10px; color: var(--text-3); }
.batch-timer strong { font-size: 20px; color: var(--accent); line-height: 1.1; }
.batch-timer.urgent strong { color: var(--danger); }
.bt-sub { font-size: 10px; color: var(--text-3); }

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1px;
  background: var(--border);
}
.scenario-card {
  background: var(--panel);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 13px;
  position: relative;
}
.scenario-card.recommended { background: color-mix(in srgb, var(--panel-solid) 86%, var(--accent)); }
.scenario-card.recommended::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
}
.sc-head { display: flex; align-items: center; gap: 10px; }
.sc-letter {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 700;
  flex: none;
}
.sc-A { color: var(--accent); background: var(--accent-soft); border: 1px solid var(--accent-line); }
.sc-B { color: var(--blue); background: var(--blue-soft); border: 1px solid color-mix(in srgb, var(--blue) 30%, transparent); }
.sc-C { color: var(--violet); background: var(--violet-soft); border: 1px solid color-mix(in srgb, var(--violet) 30%, transparent); }
.sc-title { flex: 1; min-width: 0; }
.sc-title strong { display: block; font-size: 12.5px; }
.sc-title span { font-size: 10.5px; color: var(--text-3); }

.sc-score {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  border: 1px solid var(--border);
}
.sc-score-meta { display: flex; flex-direction: column; gap: 5px; flex: 1; }
.sc-score-meta > div { display: flex; justify-content: space-between; align-items: baseline; font-size: 11px; color: var(--text-3); }
.sc-score-meta strong { font-size: 13px; color: var(--text); }

.sc-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.sc-kpis > div {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
  padding: 7px 9px;
  border-radius: 7px;
  background: var(--panel-inset);
  font-size: 10.5px;
  color: var(--text-3);
}
.sc-kpis strong { font-size: 12px; color: var(--text-2); font-variant-numeric: tabular-nums; }

.sc-weights { display: flex; flex-direction: column; gap: 6px; }
.weight-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  color: var(--text-3);
}
.weight-line > span { width: 30px; flex: none; }
.weight-track {
  flex: 1;
  height: 5px;
  border-radius: 99px;
  background: var(--panel-inset);
  overflow: hidden;
}
.weight-track > i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--teal));
}
.weight-line em { font-style: normal; color: var(--text-2); width: 30px; text-align: right; }
.weight-line.big > span { width: 38px; font-size: 11.5px; }
.weight-line.big .weight-track { height: 7px; }
.weight-line.big em { width: 38px; font-size: 11.5px; }

.sc-flags { display: flex; flex-wrap: wrap; gap: 6px; }
.sc-actions { display: flex; gap: 7px; margin-top: auto; }

.empty-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  padding: 56px 20px;
  text-align: center;
}
.empty-block h3 { font-size: 16px; }
.empty-block .btn { margin-top: 6px; }

.data-table tbody tr { cursor: pointer; }

/* drawer */
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; flex-wrap: wrap; }
.detail-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 700;
}
.detail-title { font-size: 18px; font-weight: 720; margin-top: 4px; }
.detail-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 6px; font-size: 11px; color: var(--text-3); }
.detail-score { display: flex; align-items: center; gap: 11px; }
.detail-score span { display: block; font-size: 10px; color: var(--text-3); }
.detail-score strong { font-size: 21px; }
.detail-loading { display: flex; align-items: center; gap: 10px; padding: 50px 0; justify-content: center; color: var(--text-3); font-size: 12px; }
.sibling-strip { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-bottom: 14px; }
.sibling-strip .chip { height: 25px; font-size: 11px; }
.sibling-strip .chip:disabled { cursor: default; opacity: 1; }
.sibling-spacer { flex: 1; }

.detail-kpis {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
}
.dk {
  padding: 10px 11px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.dk span { font-size: 10px; color: var(--text-3); }
.dk strong { font-size: 15px; }

.detail-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr);
  gap: 22px;
}
.drawer-section { margin-bottom: 20px; }
.drawer-section:last-child { margin-bottom: 0; }
.section-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text-2);
  margin-bottom: 10px;
}
.section-title .badge { margin-left: auto; }

.reason-list { display: flex; flex-direction: column; gap: 8px; }
.reason-list li {
  display: flex;
  gap: 9px;
  padding: 9px 11px;
  border-radius: 8px;
  background: var(--panel-inset);
  border: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}
.reason-no { font-family: var(--mono); font-size: 10px; color: var(--accent); flex: none; padding-top: 2px; }
.solver-meta {
  display: grid;
  gap: 0;
  margin-top: 10px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px dashed var(--border);
}
.solver-meta > div { display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; font-size: 11px; }
.solver-meta span { color: var(--text-3); }
.solver-meta strong { color: var(--text-2); font-weight: 550; text-align: right; }

.check-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.check-cell {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  font-size: 11px;
}
.check-cell.failed { border-color: color-mix(in srgb, var(--danger) 40%, transparent); background: var(--danger-soft); }
.check-cell.skipped { border-style: dashed; opacity: 0.62; }
.check-cell.skipped .check-icon { color: var(--text-muted); }
.check-note { margin-top: 8px; }
.check-code { font-size: 9.5px; color: var(--text-3); flex: none; }
.check-title { flex: 1; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.check-icon { color: var(--success); flex: none; }
.check-cell.failed .check-icon { color: var(--danger); }

.soft-item {
  padding: 11px 13px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  background: var(--warning-soft);
  margin-bottom: 8px;
}
.soft-head { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.soft-head .mono { color: var(--warning); font-size: 10px; }
.soft-head strong { flex: 1; }
.soft-item p { font-size: 11.5px; color: var(--text-2); margin-top: 4px; }
.soft-samples { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.soft-samples .chip { height: 22px; font-size: 10px; }

.diff-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
  margin-bottom: 9px;
}
.diff-summary > div {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 10px;
  border-radius: 7px;
  background: var(--panel-inset);
  font-size: 10.5px;
  color: var(--text-3);
}
.diff-summary strong { font-size: 14px; color: var(--text); }
.diff-table { max-height: 280px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
.diff-table .data-table { min-width: 620px; }
.diff-table th { background: var(--panel-solid); }

.weights-block {
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.approval-card {
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.approval-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.approval-card .kv { padding: 7px 0; font-size: 11.5px; }
.approval-card .v.hash { font-size: 9.5px; max-width: 62%; }
.approval-comment {
  margin-top: 8px;
  padding: 9px 11px;
  border-radius: 7px;
  background: var(--panel-solid);
  border-left: 2px solid var(--accent);
  font-size: 11.5px;
  color: var(--text-2);
}
.approval-actions { display: flex; flex-direction: column; gap: 8px; margin-top: 11px; }
.applied-note {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  margin-top: 10px;
  border-radius: 8px;
  background: var(--success-soft);
  color: var(--success);
  font-size: 11.5px;
  line-height: 1.55;
}

.prov-flow { display: flex; flex-direction: column; gap: 4px; }
.prov-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  position: relative;
}
.prov-node + .prov-node::before {
  content: '';
  position: absolute;
  top: -5px;
  left: 17px;
  width: 1px;
  height: 4px;
  background: var(--border-strong);
}
.prov-type {
  font-size: 9px;
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 4px;
  flex: none;
}
.prov-node strong { font-size: 11px; font-weight: 550; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prov-node.type-approval { border-color: var(--accent-line); }
.prov-node.type-solver { border-color: color-mix(in srgb, var(--teal) 30%, transparent); }
.prov-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  font-size: 9.5px;
  color: var(--text-3);
  font-family: var(--mono);
}
.feedback-actions { display: flex; gap: 7px; }
.domain-counts { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
.domain-counts .chip { height: 24px; font-size: 10.5px; }
.domain-counts em { font-style: normal; color: var(--accent); }

/* signature modal */
.sign-body { display: flex; flex-direction: column; gap: 14px; }
.sign-summary {
  padding: 11px 13px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.sign-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 5px 0;
  font-size: 12px;
}
.sign-row span:first-child { color: var(--text-3); }
.sign-shield {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  color: var(--accent);
}
.sign-shield p { font-size: 11.5px; line-height: 1.6; }
.sign-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 10.5px;
  color: var(--text-3);
}
.sign-meta span { display: inline-flex; align-items: center; gap: 5px; }
.sign-error {
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

@media (max-width: 1279px) {
  .review-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .scenario-grid { grid-template-columns: 1fr; }
  .detail-kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .detail-columns { grid-template-columns: 1fr; }
}
@media (max-width: 767px) {
  .review-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .review-stat strong { font-size: 20px; }
  .filter-bar { align-items: flex-start; }
  .filter-hint { display: none; }
  .batch-head { padding: 14px; }
  .batch-timer { width: 100%; flex-direction: row; align-items: center; justify-content: space-between; }
  .batch-timer strong { font-size: 17px; }
  .scenario-card { padding: 14px; }
  .sc-actions { flex-wrap: wrap; }
  .detail-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .check-grid { grid-template-columns: 1fr; }
  .sibling-strip { gap: 5px; }
  .sibling-spacer { display: none; }
  .sign-row { font-size: 11.5px; }
}
</style>
