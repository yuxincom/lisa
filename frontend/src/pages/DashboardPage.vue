<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { alertsApi, dashboardApi } from '@/api'
import { useAsync } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import {
  DOMAIN_COLOR,
  SEVERITY_LABEL,
  SCENARIO_LABEL,
  actionLabel,
  alertTone,
  formatDateTime,
  formatHours,
  formatNumber,
  formatPercent,
  formatTime,
  relativeTime,
  statusTone,
  truncateMiddle,
} from '@/utils/format'
import { chartTheme, withAlpha } from '@/utils/chart'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import RingGauge from '@/components/RingGauge.vue'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'
import Sparkline from '@/components/Sparkline.vue'

const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const { data, loading, error, refresh } = useAsync(() => dashboardApi.overview())
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => void refresh(), 90_000)
  window.addEventListener('lisa:refresh-shell', refresh)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  window.removeEventListener('lisa:refresh-shell', refresh)
})

const baseline = computed(() => data.value?.baseline || null)
const approvalList = computed(() =>
  [...(data.value?.approvals || [])].sort((a, b) => (a.approval?.minutes_left ?? 999) - (b.approval?.minutes_left ?? 999)),
)
const resourceLoad = computed(() => [...(data.value?.resource_load || [])].sort((a, b) => b.load - a.load).slice(0, 9))
const alerts = computed(() => (data.value?.alerts || []).slice(0, 5))
const changes = computed(() => (data.value?.changes || []).filter((item) => item.status !== '已关闭').slice(0, 3))
const riskOrders = computed(() => data.value?.risk_orders || [])
const quality = computed(() => data.value?.quality || null)
const kit = computed(() => data.value?.kit || null)
const domainWorkload = computed(() => data.value?.domain_workload || [])
const totalDomainHours = computed(() => domainWorkload.value.reduce((sum, item) => sum + item.hours, 0))
const maxDomainHours = computed(() => Math.max(1, ...domainWorkload.value.map((item) => item.hours)))

function remaining(minutes?: number | null): string {
  if (minutes === undefined || minutes === null) return '待计算'
  if (minutes <= 0) return '已超时'
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))} 分钟`
  return `${(minutes / 60).toFixed(1)} 小时`
}

function urgency(minutes?: number | null): string {
  if (minutes === undefined || minutes === null) return 'badge-muted'
  if (minutes <= 5) return 'badge-danger'
  if (minutes <= 20) return 'badge-warning'
  return 'badge-teal'
}

function barColor(load: number): string {
  if (load >= 85) return 'var(--danger)'
  if (load >= 70) return 'var(--warning)'
  return 'var(--teal)'
}

const domainOption = computed(() => {
  const t = chartTheme()
  const dark = ui.theme === 'dark'
  const list = domainWorkload.value
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: withAlpha(t.text3, 0.08) } },
    },
    legend: { right: 0, top: 0, itemWidth: 8, itemHeight: 8, textStyle: { color: t.text3, fontSize: 11 } },
    grid: { left: 8, right: 6, top: 40, bottom: 0, containLabel: true },
    xAxis: {
      type: 'category',
      data: list.map((item) => item.domain),
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { show: false },
      axisLabel: { color: t.text3, fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        name: '工时',
        nameTextStyle: { color: t.text3, fontSize: 10 },
        axisLabel: { color: t.text3, fontSize: 10 },
        splitLine: { lineStyle: { color: withAlpha(t.text3, dark ? 0.14 : 0.2), type: 'dashed' } },
      },
      {
        type: 'value',
        name: '负荷',
        max: 100,
        nameTextStyle: { color: t.text3, fontSize: 10 },
        axisLabel: { color: t.text3, fontSize: 10, formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '计划工时',
        type: 'bar',
        barWidth: 18,
        data: list.map((item) => ({
          value: item.hours,
          itemStyle: {
            color: withAlpha(DOMAIN_COLOR[item.domain] || t.blue, 0.82),
            borderRadius: [4, 4, 2, 2],
          },
        })),
        emphasis: { itemStyle: { color: DOMAIN_COLOR[list[0]?.domain] || t.accent } },
      },
      {
        name: '负荷率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: list.map((item) => item.load),
        lineStyle: { width: 2, color: t.teal },
        itemStyle: { color: t.teal, borderColor: t.panel, borderWidth: 2 },
        areaStyle: { color: withAlpha(t.teal, 0.1) },
      },
    ],
  }
})

const resourceOption = computed(() => {
  const t = chartTheme()
  const list = [...resourceLoad.value].reverse()
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: withAlpha(t.text3, 0.08) } },
      valueFormatter: (value: number) => `${Number(value).toFixed(1)}%`,
    },
    grid: { left: 4, right: 40, top: 10, bottom: 0, containLabel: true },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: t.text3, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: withAlpha(t.text3, 0.14), type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: list.map((item) => `${item.code} · ${item.resource}`),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.text2, fontSize: 10.5, width: 148, overflow: 'truncate' },
    },
    series: [
      {
        name: '负荷率',
        type: 'bar',
        barWidth: 12,
        showBackground: true,
        backgroundStyle: { color: withAlpha(t.text3, 0.09), borderRadius: 8 },
        data: list.map((item) => ({
          value: item.load,
          itemStyle: {
            color: item.bottleneck
              ? `linear-gradient(90deg, ${withAlpha(t.danger, 0.55)}, ${t.danger})`
              : `linear-gradient(90deg, ${withAlpha(t.teal, 0.45)}, ${t.teal})`,
            borderRadius: 8,
          },
        })),
        label: {
          show: true,
          position: 'right',
          color: t.text2,
          fontSize: 10,
          formatter: '{c}%',
        },
      },
    ],
  }
})

async function ack(id: number) {
  try {
    await alertsApi.ackOne(id)
    ui.success('告警已确认', '处置动作已写入哈希审计链')
    await refresh()
  } catch (err) {
    ui.error('确认失败', err instanceof Error ? err.message : '请稍后重试')
  }
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="COMMAND COCKPIT · 决策层"
      title="指挥驾驶舱"
      subtitle="全厂排产态势、L0 数据门禁、变更涟漪与审批链路实时汇聚，支撑生产指挥部分钟级决策。"
    >
      <template #actions>
        <button class="btn btn-sm" :disabled="loading" @click="refresh()">
          <span v-if="loading" class="spinner" />
          <AppIcon v-else name="refresh" :size="15" />
          刷新态势
        </button>
        <router-link class="btn btn-sm btn-teal" to="/gantt">
          <AppIcon name="gantt" :size="15" />
          智能排产
        </router-link>
      </template>
      <template #meta>
        <div class="flex items-center gap-10 fs-12 muted">
          <span class="flex items-center gap-6"><span class="dot dot-live" />实时接入</span>
          <span class="hide-mobile">更新于 {{ formatDateTime(data?.system?.generated_at as string) }}</span>
        </div>
      </template>
    </PageHeader>

    <div v-if="error" class="panel gate-error">
      <AppIcon name="warning" :size="20" />
      <div>
        <strong>态势数据加载失败</strong>
        <p class="fs-12 muted">{{ error }}</p>
      </div>
      <button class="btn btn-sm" @click="refresh()">重试</button>
    </div>

    <template v-if="data">
      <section class="baseline-hero panel">
        <div class="hero-beam" />
        <div class="hero-left">
          <div class="hero-eyebrow">
            <span class="dot dot-live" />
            ACTIVE BASELINE · 生效基线
          </div>
          <template v-if="baseline">
            <div class="hero-code mono">{{ baseline.code }}</div>
            <div class="hero-objective">{{ baseline.objective }}</div>
            <div class="hero-meta">
              <span><AppIcon name="shield" :size="13" /> 写保护网关已签发</span>
              <span><AppIcon name="clock" :size="13" /> {{ formatDateTime(baseline.applied_at) }}</span>
              <span><AppIcon name="lock" :size="13" /> 冻结 {{ baseline.summary?.locked_operations ?? 0 }} 道工序</span>
            </div>
          </template>
          <template v-else>
            <div class="hero-code mono">NO BASELINE</div>
            <div class="hero-objective">尚未签发生产基线</div>
            <div class="hero-meta"><span>请前往方案审批完成电子签名终审</span></div>
          </template>
        </div>

        <div v-if="baseline" class="hero-metrics">
          <div class="hero-metric">
            <span class="hm-label">准时交付率</span>
            <span class="hm-value num">{{ formatPercent(baseline.kpi?.on_time_rate, 1) }}</span>
            <span class="hm-foot">逾期 {{ baseline.kpi?.late_orders ?? 0 }} 单</span>
          </div>
          <div class="hero-metric">
            <span class="hm-label">排产采纳率</span>
            <span class="hm-value num">{{ formatPercent(baseline.kpi?.predicted_adoption, 1) }}</span>
            <span class="hm-foot">目标 ≥ 85%</span>
          </div>
          <div class="hero-metric">
            <span class="hm-label">覆盖工序</span>
            <span class="hm-value num">{{ formatNumber(baseline.kpi?.operations) }}</span>
            <span class="hm-foot">{{ baseline.kpi?.orders ?? 0 }} 个订单</span>
          </div>
          <div class="hero-metric">
            <span class="hm-label">换型时间</span>
            <span class="hm-value num">{{ formatHours(baseline.kpi?.changeover_minutes) }}</span>
            <span class="hm-foot">{{ baseline.kpi?.changeover_count ?? 0 }} 次换型</span>
          </div>
        </div>

        <div class="hero-actions">
          <div class="approval-chip" :class="{ urgent: (data.approvals?.[0]?.approval?.minutes_left ?? 99) <= 15 }" @click="router.push('/plans')">
            <span class="chip-icon"><AppIcon name="approval" :size="16" /></span>
            <div>
              <strong>{{ data.pending_batches }} 批方案待终审</strong>
              <small>15 分钟内完成电子签名</small>
            </div>
            <AppIcon name="chevrons" :size="15" />
          </div>
          <div class="order-chips">
            <span v-for="status in data.order_status" :key="status.status" class="order-chip">
              <em :class="statusTone(status.status)">{{ status.count }}</em>
              {{ status.status }}
            </span>
          </div>
        </div>
      </section>

      <section class="grid grid-kpi kpi-grid">
        <StatCard v-for="kpi in data.kpis" :key="kpi.key" :kpi="kpi" />
      </section>

      <section class="grid grid-2-1">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />全域负荷与工时分布</div>
            <div class="panel-sub">七域 {{ formatNumber(totalDomainHours, 1) }} 工时 · 负荷率加权</div>
          </div>
          <div class="panel-body">
            <EChart :option="domainOption" height="286px" :loading="loading" />
            <div class="domain-strip">
              <div v-for="item in domainWorkload" :key="item.domain" class="domain-strip-item">
                <i :style="{ background: DOMAIN_COLOR[item.domain] }" />
                <span>{{ item.domain }}</span>
                <em class="num">{{ item.operations }} 工序</em>
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />L0 数据门禁</div>
            <StatusBadge :status="quality?.gate?.passed ? 'passed' : 'blocked'" :label="quality?.gate?.label || '待检测'" :tone="quality?.gate?.passed ? 'success' : 'danger'" />
          </div>
          <div class="panel-body quality-body">
            <div class="quality-ring">
              <RingGauge
                :value="quality?.overall ?? 0"
                :size="138"
                :stroke="10"
                :color="quality?.gate?.passed ? 'var(--success)' : 'var(--danger)'"
                label="综合质量分"
                :sublabel="`阈值 ${quality?.threshold ?? 90}`"
              />
              <p class="quality-gate">{{ quality?.gate?.message }}</p>
            </div>
            <div class="quality-dims">
              <div v-for="dim in quality?.dimensions || []" :key="dim.key" class="dim-row">
                <div class="dim-head">
                  <span>{{ dim.label || dim.key }}</span>
                  <span class="num" :class="dim.passed ? 'text-success' : 'text-danger'">{{ dim.score.toFixed(1) }}</span>
                </div>
                <div class="progress"><i :style="{ width: `${dim.score}%`, background: dim.passed ? undefined : 'var(--danger)' }" /></div>
              </div>
            </div>
          </div>
          <div class="panel-foot flex justify-between items-center">
            <span>五维点检 · 低于阈值自动阻断排产链路</span>
            <router-link class="link" to="/data">数据底座 <AppIcon name="external" :size="12" /></router-link>
          </div>
        </div>
      </section>

      <section class="grid grid-2-1">
        <div class="panel approvals-panel">
          <div class="panel-head">
            <div class="panel-title">
              <span class="title-mark" />待终审方案
              <span class="badge badge-accent">{{ data.pending_batches }} 批</span>
            </div>
            <router-link class="link" to="/plans">审批中心 <AppIcon name="chevrons" :size="13" /></router-link>
          </div>
          <div class="panel-body flush">
            <div v-if="!approvalList.length" class="empty">
              <span class="empty-icon"><AppIcon name="check" :size="20" /></span>
              暂无待审批方案，基线保持稳定
            </div>
            <article v-for="plan in approvalList" :key="plan.id" class="approval-row" @click="router.push({ path: '/plans', query: { plan: plan.id } })">
              <div class="ar-left">
                <span class="scenario-pill" :class="`scenario-${plan.scenario}`">{{ plan.scenario }}</span>
                <div class="ar-main">
                  <div class="ar-title">{{ plan.name }}</div>
                  <div class="ar-meta">
                    <span class="mono">{{ plan.code }}</span>
                    <span>{{ plan.summary?.operations }} 工序</span>
                    <span>{{ plan.diff?.moved }} 移动作业</span>
                    <span>{{ plan.created_by }}</span>
                  </div>
                </div>
              </div>
              <div class="ar-scores">
                <div><span>评分</span><strong class="num">{{ plan.kpi?.total_score?.toFixed(1) }}</strong></div>
                <div><span>准时率</span><strong class="num text-teal">{{ formatPercent(plan.kpi?.on_time_rate, 1) }}</strong></div>
                <div><span>锁定</span><strong class="num">{{ plan.kpi?.locked_operations }}</strong></div>
              </div>
              <div class="ar-time">
                <span class="badge" :class="urgency(plan.approval?.minutes_left)">
                  <AppIcon name="clock" :size="11" />
                  {{ plan.approval?.escalated ? '已升级' : remaining(plan.approval?.minutes_left) }}
                </span>
                <span class="ar-created">{{ relativeTime(plan.created_at) }}</span>
              </div>
              <AppIcon name="chevrons" :size="15" class="ar-arrow" />
            </article>
          </div>
          <div class="panel-foot flex justify-between items-center">
            <span>电子签名 + 写保护网关双校验后写入 APS/MES</span>
            <button v-if="auth.can('plans:approve')" class="link" @click="router.push('/plans')">立即终审 →</button>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div class="panel-title">
              <span class="title-mark" />实时告警
              <span v-if="data.alert_counts?.open" class="badge badge-danger">{{ data.alert_counts.open }}</span>
            </div>
            <router-link class="link" to="/alerts">全部 <AppIcon name="chevrons" :size="13" /></router-link>
          </div>
          <div class="panel-body flush alert-list">
            <div v-if="!alerts.length" class="empty">暂无告警，系统运行平稳</div>
            <article v-for="alert in alerts" :key="alert.id" class="alert-row">
              <span class="alert-bar" :class="`tone-${alertTone(alert.level)}`" />
              <div class="alert-main">
                <div class="alert-title">
                  {{ alert.title }}
                  <span class="badge" :class="`badge-${alertTone(alert.level)}`">{{ alert.level_label }}</span>
                </div>
                <p class="alert-msg">{{ alert.message }}</p>
                <div class="alert-meta">{{ alert.source }} · {{ relativeTime(alert.created_at) }}</div>
              </div>
              <button
                v-if="auth.can('alerts:ack') && alert.status === 'open'"
                class="btn btn-sm btn-ghost"
                @click="ack(alert.id)"
              >
                确认
              </button>
              <span v-else class="badge badge-muted">{{ alert.status === 'acked' ? '已确认' : alert.status }}</span>
            </article>
          </div>
        </div>
      </section>

      <section class="grid grid-2">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />瓶颈资源负荷 TOP</div>
            <div class="panel-sub">按当前基线 · 负荷率</div>
          </div>
          <div class="panel-body">
            <EChart :option="resourceOption" height="272px" />
          </div>
          <div class="panel-foot flex justify-between items-center">
            <span class="flex items-center gap-6"><span class="dot" style="background: var(--warning)" />预警 ≥ 70%</span>
            <span class="flex items-center gap-6"><span class="dot" style="background: var(--danger)" />瓶颈 ≥ 85%</span>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />齐套三时点</div>
            <div class="panel-sub">目标 100% · 九要素校验</div>
          </div>
          <div class="panel-body">
            <div class="kit-cards">
              <div v-for="cp in kit?.by_checkpoint || []" :key="cp.checkpoint" class="kit-card">
                <div class="kit-card-head">
                  <span>{{ cp.label }}</span>
                  <strong class="num" :class="cp.rate >= 95 ? 'text-success' : cp.rate >= 85 ? 'text-warning' : 'text-danger'">
                    {{ formatPercent(cp.rate, 1) }}
                  </strong>
                </div>
                <div class="progress kit-progress">
                  <i
                    :style="{
                      width: `${cp.rate}%`,
                      background: cp.rate >= 95 ? 'var(--success)' : cp.rate >= 85 ? 'var(--warning)' : 'var(--danger)',
                    }"
                  />
                </div>
                <div class="kit-card-foot">
                  <span>{{ cp.passed }}/{{ cp.total }} 齐套</span>
                  <span v-if="cp.missing" class="text-warning">缺项 {{ cp.missing }}</span>
                  <span v-if="cp.blocked" class="text-danger">阻断 {{ cp.blocked }}</span>
                </div>
              </div>
            </div>
            <div class="gap-owners">
              <div class="gap-title">缺口责任分布</div>
              <div class="flex wrap gap-6">
                <router-link
                  v-for="owner in kit?.gap_owners || []"
                  :key="owner.owner"
                  class="chip"
                  to="/kits"
                >
                  {{ owner.owner }}
                  <span class="num text-accent">{{ owner.count }}</span>
                </router-link>
              </div>
            </div>
          </div>
          <div class="panel-foot flex justify-between items-center">
            <span>更新于 {{ formatTime(kit?.updated_at) }}</span>
            <router-link class="link" to="/kits">齐套检查 <AppIcon name="chevrons" :size="12" /></router-link>
          </div>
        </div>
      </section>

      <section class="grid grid-3">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />智能体运行动态</div>
            <router-link class="link" to="/agents">运行中心</router-link>
          </div>
          <div class="panel-body flush">
            <div v-if="!data.recent_runs?.length" class="empty">暂无运行记录</div>
            <article v-for="run in data.recent_runs.slice(0, 5)" :key="run.code" class="run-row">
              <span class="run-level">{{ run.level }}</span>
              <div class="grow">
                <div class="run-summary">{{ run.summary }}</div>
                <div class="run-meta">
                  <span class="mono">{{ run.agent_code }}</span>
                  <span>{{ relativeTime(run.started_at) }}</span>
                  <span>{{ run.simulated_minutes }} min</span>
                </div>
              </div>
              <StatusBadge :status="run.status" :label="run.status === 'succeeded' ? '成功' : run.status" />
            </article>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />审计哈希链</div>
            <router-link class="link" to="/audit">全量审计</router-link>
          </div>
          <div class="panel-body flush">
            <article v-for="log in data.audit_tail.slice(0, 5)" :key="log.id" class="audit-row">
              <span class="audit-seq num">#{{ log.seq }}</span>
              <div class="grow">
                <div class="audit-action">{{ actionLabel(log.action) }}</div>
                <div class="audit-meta">
                  <span>{{ log.actor }} · {{ log.role }}</span>
                  <span>{{ formatTime(log.ts) }}</span>
                </div>
                <div class="hash">{{ truncateMiddle(log.hash, 18, 10) }}</div>
              </div>
              <span class="badge" :class="log.result === 'success' ? 'badge-success' : 'badge-danger'">
                {{ log.result === 'success' ? '成功' : log.result }}
              </span>
            </article>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />扰动与交期风险</div>
            <router-link class="link" to="/changes">变更影响</router-link>
          </div>
          <div class="panel-body">
            <div v-if="!changes.length && !riskOrders.length" class="empty">当前无未关闭扰动</div>
            <div v-for="change in changes" :key="change.id" class="risk-change" @click="router.push({ path: '/changes', query: { change: change.id } })">
              <div class="rc-head">
                <span class="badge" :class="change.severity === 'critical' ? 'badge-danger' : 'badge-warning'">
                  {{ SEVERITY_LABEL[change.severity] || change.severity }}
                </span>
                <span class="mono fs-12 muted">{{ change.code }}</span>
              </div>
              <div class="rc-title">{{ change.title }}</div>
              <div class="rc-meta">
                <span>{{ formatDateTime(change.occurred_at) }}</span>
                <span v-if="change.impact">影响 {{ change.impact.summary.affected_orders }} 单</span>
                <span>{{ change.status }}</span>
              </div>
            </div>
            <div v-if="riskOrders.length" class="risk-list">
              <div class="risk-list-title">交期风险订单</div>
              <div v-for="order in riskOrders.slice(0, 3)" :key="order.order_no" class="risk-order">
                <span class="mono">{{ order.order_no }}</span>
                <span class="truncate">{{ order.product_name }}</span>
                <span class="badge badge-danger">+{{ order.late_hours }}h</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />订单交付风险台账</div>
          <div class="flex items-center gap-8">
            <span class="panel-sub">逾期与紧张订单优先暴露</span>
            <router-link class="btn btn-sm btn-ghost" to="/orders">订单台账</router-link>
          </div>
        </div>
        <div class="panel-body flush">
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>订单号</th>
                  <th>产品</th>
                  <th>优先级</th>
                  <th>交期</th>
                  <th>预计完工</th>
                  <th>偏差</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="order in riskOrders.slice(0, 8)" :key="order.order_no" @click="router.push({ path: '/orders', query: { order: order.order_id } })">
                  <td class="cell-strong mono">{{ order.order_no }}</td>
                  <td>{{ order.product_name }}</td>
                  <td><span class="priority" :class="`priority-${order.priority}`">{{ order.priority }}</span></td>
                  <td>{{ formatDateTime(order.due_date) }}</td>
                  <td>{{ formatDateTime(order.scheduled_finish) }}</td>
                  <td>
                    <span class="badge" :class="order.late_hours > 0 ? 'badge-danger' : 'badge-teal'">
                      {{ order.late_hours > 0 ? `+${order.late_hours}h` : '可交付' }}
                    </span>
                  </td>
                  <td><StatusBadge :status="order.late_hours > 0 ? 'late' : 'normal'" :label="order.late_hours > 0 ? '逾期风险' : '正常'" /></td>
                </tr>
                <tr v-if="!riskOrders.length">
                  <td colspan="7">
                    <div class="empty">当前基线无逾期或紧张订单</div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>

    <div v-else-if="loading" class="grid grid-kpi kpi-grid">
      <div v-for="n in 8" :key="n" class="skeleton" style="height: 140px" />
    </div>
  </div>
</template>

<style scoped>
.gate-error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-color: color-mix(in srgb, var(--danger) 40%, transparent);
  color: var(--danger);
  margin-bottom: 16px;
}
.gate-error .grow,
.gate-error div {
  flex: 1;
}

/* Baseline hero */
.baseline-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1.3fr) minmax(0, 0.9fr);
  gap: 22px;
  align-items: center;
  padding: 22px 24px;
  margin-bottom: 16px;
  border-color: var(--border-accent);
  background:
    linear-gradient(115deg, rgba(240, 164, 58, 0.09), transparent 45%),
    var(--panel);
}
.hero-beam {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--accent), var(--teal));
  box-shadow: 0 0 18px var(--accent-line);
}
.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--accent);
  text-transform: uppercase;
}
.hero-code {
  margin-top: 8px;
  font-size: clamp(19px, 2vw, 25px);
  color: var(--text);
  letter-spacing: 0.01em;
}
.hero-objective {
  margin-top: 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
}
.hero-meta {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 11.5px;
  color: var(--text-3);
}
.hero-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.hero-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.hero-metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px 13px;
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  border: 1px solid var(--border);
}
.hm-label {
  font-size: 11px;
  color: var(--text-3);
}
.hm-value {
  font-size: 21px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.15;
}
.hm-foot {
  font-size: 10.5px;
  color: var(--text-3);
}
.hero-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.approval-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease;
}
.approval-chip:hover {
  transform: translateY(-1px);
  border-color: var(--accent);
}
.approval-chip.urgent {
  border-color: color-mix(in srgb, var(--danger) 45%, transparent);
  background: var(--danger-soft);
}
.chip-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--panel-solid);
  color: var(--accent);
  flex: none;
}
.approval-chip > div {
  flex: 1;
  min-width: 0;
}
.approval-chip strong {
  display: block;
  font-size: 13px;
}
.approval-chip small {
  font-size: 11px;
  color: var(--text-3);
}
.order-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.order-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-3);
}
.order-chip em {
  font-style: normal;
  font-weight: 700;
  color: var(--text);
  font-family: var(--mono);
}
.order-chip em.success { color: var(--success); }
.order-chip em.warning { color: var(--warning); }
.order-chip em.danger { color: var(--danger); }

.kpi-grid {
  margin-bottom: 16px;
}
.grid + .grid {
  margin-top: 16px;
}

.domain-strip {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.domain-strip-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-2);
}
.domain-strip-item i {
  width: 16px;
  height: 3px;
  border-radius: 2px;
  margin-bottom: 3px;
}
.domain-strip-item em {
  font-style: normal;
  font-size: 10px;
  color: var(--text-3);
}

.quality-body {
  display: flex;
  gap: 20px;
  align-items: center;
}
.quality-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  flex: none;
  width: 150px;
}
.quality-gate {
  font-size: 11px;
  color: var(--text-3);
  text-align: center;
  line-height: 1.5;
}
.quality-dims {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.dim-head {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-2);
  margin-bottom: 5px;
}
.dim-head .num {
  font-weight: 650;
}

/* Approvals */
.approval-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background-color 0.16s ease;
}
.approval-row:last-child { border-bottom: none; }
.approval-row:hover { background: var(--panel-hover); }
.ar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1.5;
  min-width: 0;
}
.scenario-pill {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  font-family: var(--mono);
  font-weight: 700;
  font-size: 13px;
  flex: none;
}
.scenario-A { color: var(--accent); background: var(--accent-soft); border: 1px solid var(--accent-line); }
.scenario-B { color: var(--blue); background: var(--blue-soft); border: 1px solid color-mix(in srgb, var(--blue) 30%, transparent); }
.scenario-C { color: var(--violet); background: var(--violet-soft); border: 1px solid color-mix(in srgb, var(--violet) 30%, transparent); }
.ar-main { min-width: 0; }
.ar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ar-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 10.5px;
  color: var(--text-3);
  margin-top: 2px;
}
.ar-scores {
  display: flex;
  gap: 15px;
  flex: none;
}
.ar-scores > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.ar-scores span {
  font-size: 10px;
  color: var(--text-3);
}
.ar-scores strong {
  font-size: 14.5px;
  color: var(--text);
}
.ar-time {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex: none;
  width: 92px;
}
.ar-created { font-size: 10px; color: var(--text-3); }
.ar-arrow { color: var(--text-3); flex: none; }

/* Alerts */
.alert-list { max-height: 360px; overflow-y: auto; }
.alert-row {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.alert-row:last-child { border-bottom: none; }
.alert-bar {
  width: 3px;
  align-self: stretch;
  border-radius: 3px;
  flex: none;
  background: var(--text-3);
}
.alert-bar.tone-danger { background: var(--danger); }
.alert-bar.tone-warning { background: var(--warning); }
.alert-bar.tone-blue { background: var(--blue); }
.alert-main { flex: 1; min-width: 0; }
.alert-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  flex-wrap: wrap;
}
.alert-msg {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.alert-meta { font-size: 10px; color: var(--text-3); margin-top: 4px; }

.kit-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.kit-card {
  padding: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.kit-card-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 11.5px;
  color: var(--text-2);
}
.kit-card-head strong { font-size: 15px; }
.kit-progress { margin: 7px 0 6px; }
.kit-card-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 10px;
  color: var(--text-3);
}
.gap-owners { margin-top: 16px; }
.gap-title { font-size: 11.5px; color: var(--text-3); margin-bottom: 8px; }
.gap-owners .chip { height: 26px; font-size: 11px; }

.run-row,
.audit-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--border);
}
.run-row:last-child,
.audit-row:last-child { border-bottom: none; }
.run-level {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: var(--panel-strong);
  border: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 700;
  color: var(--teal);
  flex: none;
}
.run-summary {
  font-size: 11.8px;
  color: var(--text-2);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.run-meta,
.audit-meta {
  display: flex;
  gap: 10px;
  font-size: 10px;
  color: var(--text-3);
  margin-top: 2px;
}
.run-row :deep(.badge) { flex: none; }
.audit-seq {
  font-size: 11px;
  color: var(--text-3);
  width: 30px;
  flex: none;
}
.audit-action { font-size: 12px; color: var(--text); font-weight: 550; }
.audit-row .hash { margin-top: 1px; }

.risk-change {
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
  margin-bottom: 9px;
  cursor: pointer;
  transition: border-color 0.16s ease, transform 0.16s ease;
}
.risk-change:hover { border-color: var(--border-accent); transform: translateY(-1px); }
.rc-head { display: flex; justify-content: space-between; align-items: center; }
.rc-title { font-size: 12.5px; font-weight: 600; color: var(--text); margin-top: 6px; }
.rc-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: 10px; color: var(--text-3); margin-top: 3px; }
.risk-list { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 10px; }
.risk-list-title { font-size: 11px; color: var(--text-3); margin-bottom: 6px; }
.risk-order {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-2);
  padding: 4px 0;
}
.risk-order .mono { flex: none; }
.risk-order .truncate { flex: 1; }
.risk-order :deep(.badge) { flex: none; }

.link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  color: var(--accent);
  background: none;
  border: 0;
  padding: 0;
  transition: opacity 0.16s ease;
}
.link:hover { opacity: 0.75; }

.data-table tbody tr { cursor: pointer; }

@media (max-width: 1279px) {
  .baseline-hero {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  .hero-actions {
    grid-column: span 2;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  .approval-chip { min-width: 260px; }
  .hero-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@media (max-width: 1023px) {
  .baseline-hero { grid-template-columns: 1fr; }
  .hero-actions { grid-column: auto; flex-direction: column; align-items: stretch; }
  .quality-body { flex-direction: column; align-items: stretch; }
  .quality-ring { width: 100%; flex-direction: row; justify-content: center; gap: 16px; }
  .quality-gate { text-align: left; max-width: 180px; }
}
@media (max-width: 767px) {
  .baseline-hero { padding: 18px 16px; }
  .hero-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .hero-code { font-size: 18px; }
  .domain-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .approval-row {
    flex-wrap: wrap;
    gap: 8px;
  }
  .ar-left { flex-basis: 100%; }
  .ar-scores { flex: 1; gap: 18px; }
  .ar-time { align-items: flex-end; width: auto; }
  .ar-arrow { display: none; }
  .kit-cards { grid-template-columns: 1fr; }
  .quality-ring { flex-direction: column; }
  .quality-gate { max-width: none; text-align: center; }
}
</style>
