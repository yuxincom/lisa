<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { agentsApi, changesApi, jobsApi, mcpApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { Agent, AgentCatalog, AgentRun, Change, Job, LlmRunMeta, LlmStatus, McpCatalog, QueueHealth } from '@/types'
import {
  AGENT_LEVEL_LABEL,
  DOMAINS,
  SCENARIO_LABEL,
  formatDateTime,
  formatNumber,
  relativeTime,
  statusTone,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

const SCENARIO_OPTIONS = [
  { key: 'night', label: '夜间全量重排', agent: 'C-01', desc: 'MPS 拉动平衡 · 全量重排 · 生成 A/B/C 候选批次', minutes: '1–2 h', tone: 'accent' },
  { key: 'full', label: '全量重排', agent: 'C-01', desc: '读取全厂订单与资源快照，生成 A/B/C 多目标方案', minutes: '2 min', tone: 'teal' },
  { key: 'kit', label: '齐套全面检查', agent: 'M-03', desc: '九要素快照校验，开工前关键缺口硬阻断', minutes: '3 min', tone: 'blue' },
  { key: 'local', label: '局部重排建议', agent: 'A-00~A-06', desc: '域内产能核算与局部排产，只读建议归档', minutes: '27 min', tone: 'violet' },
  { key: 'change', label: '变更协同重排', agent: 'M-01 / M-02', desc: '读取扰动事件，涟漪推演并生成 A/B 重排方案', minutes: '13 min', tone: 'warning' },
]
const RUN_SCENARIO_LABEL: Record<string, string> = {
  full: '全量重排',
  night: '夜间全量重排',
  kit: '齐套检查',
  local: '局部重排',
  change: '变更重排',
  fault: '设备故障扰动',
  material: '物料缺料扰动',
  insert: '紧急插单',
  rework: '返工返修',
  order_change: '订单变更',
  inspection: '检测军检',
  ecn: '工艺变更',
}
const LEVEL_TONE: Record<string, string> = { C: 'accent', M: 'teal', A: 'blue' }

const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const catalog = ref<AgentCatalog | null>(null)
const runs = ref<AgentRun[]>([])
const loading = ref(false)
const error = ref('')
const levelFilter = ref('')
const agentFilter = ref('')
const scenarioFilter = ref('')
const runDetail = ref<AgentRun | null>(null)
const runDetailOpen = ref(false)
const mcp = ref<McpCatalog | null>(null)
const llm = ref<LlmStatus | null>(null)
const showToolList = ref(false)

const runOpen = ref(false)
const runScenario = ref('night')
const runChangeId = ref<number | null>(null)
const runDomain = ref('机加')
const runPlanScenario = ref('A')
const running = ref(false)
const runError = ref('')
const openChanges = ref<Change[]>([])
const activeJob = ref<Job | null>(null)
const queue = ref<QueueHealth | null>(null)
let pollTimer: number | null = null

const canRun = computed(() => auth.can('agents:run'))
const canCancelJob = computed(() => auth.can('jobs:cancel'))
const levels = computed(() => [
  { level: '', label: '全部', count: catalog.value?.summary.total || 0 },
  ...(catalog.value?.levels || []),
])
const filteredAgents = computed(() =>
  (catalog.value?.agents || []).filter((agent) => {
    if (levelFilter.value && agent.level !== levelFilter.value) return false
    if (agentFilter.value && agent.code !== agentFilter.value) return false
    return true
  }),
)
const filteredRuns = computed(() =>
  runs.value.filter((run) => {
    if (agentFilter.value && run.agent_code !== agentFilter.value) return false
    if (scenarioFilter.value && run.scenario !== scenarioFilter.value) return false
    return true
  }),
)
const currentScenarioMeta = computed(() => SCENARIO_OPTIONS.find((item) => item.key === runScenario.value))
const totalSuccess = computed(() => {
  const agents = catalog.value?.agents || []
  if (!agents.length) return 0
  return agents.reduce((sum, agent) => sum + agent.success_rate, 0) / agents.length
})
const activeAgentName = computed(() => {
  if (!agentFilter.value) return ''
  return catalog.value?.agents.find((agent) => agent.code === agentFilter.value)?.name || agentFilter.value
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [cat, runResponse, llmStatus, mcpCatalog] = await Promise.all([
      agentsApi.catalog(),
      agentsApi.runs({ limit: 60 }),
      agentsApi.llm().catch(() => null),
      mcpApi.tools().catch(() => null),
    ])
    catalog.value = cat
    runs.value = runResponse.items
    llm.value = llmStatus
    mcp.value = mcpCatalog
    void loadQueue()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function filterByAgent(agent: Agent) {
  agentFilter.value = agentFilter.value === agent.code ? '' : agent.code
}

async function openRunModal() {
  runError.value = ''
  activeJob.value = null
  running.value = false
  runScenario.value = 'night'
  runChangeId.value = null
  runDomain.value = '机加'
  runPlanScenario.value = 'A'
  runOpen.value = true
  if (!openChanges.value.length) {
    try {
      const response = await changesApi.list({ limit: 50 })
      openChanges.value = response.items.filter((change) => change.status !== '已关闭')
    } catch {
      openChanges.value = []
    }
  }
}

async function startRun() {
  if (!canRun.value) {
    ui.warning('权限不足', '当前角色没有智能体编排权限')
    return
  }
  if (runScenario.value === 'change' && !runChangeId.value) {
    runError.value = '请选择需要协同重排的扰动事件'
    return
  }
  running.value = true
  runError.value = ''
  try {
    const options: Record<string, unknown> = {}
    if (runScenario.value === 'local') {
      options.domain = runDomain.value
      options.scenario = runPlanScenario.value
    }
    const accepted = await agentsApi.run(runScenario.value, runChangeId.value, options)
    activeJob.value = accepted.job
    pollJob(accepted.job.id)
  } catch (err) {
    runError.value = errorMessage(err)
    running.value = false
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function pollJob(jobId: number) {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    let job: Job
    try {
      job = await jobsApi.get(jobId)
    } catch (err) {
      stopPolling()
      running.value = false
      runError.value = errorMessage(err)
      return
    }
    activeJob.value = job
    if (job.status === 'queued' || job.status === 'running') return
    stopPolling()
    running.value = false
    if (job.status !== 'succeeded') {
      runError.value = `${job.error.code || job.status} · ${job.error.message || '后台任务未成功结束'}`
      void loadQueue()
      return
    }
    const runId = Number(job.result.run_id)
    activeJob.value = null
    runOpen.value = false
    await load()
    if (runId) {
      runDetail.value = await agentsApi.runDetail(runId)
      runDetailOpen.value = true
      ui.success('智能体编排完成', runDetail.value.summary)
    }
  }, 1200)
}

async function loadQueue() {
  try {
    queue.value = await jobsApi.health()
  } catch {
    queue.value = null
  }
}

async function cancelJob() {
  const job = activeJob.value
  if (!job) return
  try {
    activeJob.value = await jobsApi.cancel(job.id)
    stopPolling()
    running.value = false
    ui.info('任务已取消', '仅排队中的任务可取消，已在执行的重排会跑完')
  } catch (err) {
    runError.value = errorMessage(err)
  }
}

function jobStatusText(job: Job | null): string {
  if (!job) return ''
  if (job.status === 'queued') return '排队中，等待后台 worker 领取'
  if (job.status === 'running') return `执行中 ${job.progress}%`
  if (job.status === 'succeeded') return '已完成'
  return '失败'
}

const queueWarning = computed(() => {
  if (!queue.value) return ''
  if (!queue.value.worker_enabled) return '后台 worker 未启动（LISA_JOB_WORKER=0），任务会一直排在队列里'
  if (queue.value.queued > 0 && !queue.value.worker_alive) return `有 ${queue.value.queued} 个任务在排队，但本进程 worker 未存活`
  if (queue.value.silent_workers > 0) return `${queue.value.silent_workers} 个执行进程心跳失联，等待回收`
  return ''
})

async function openRun(id: number) {
  runDetailOpen.value = true
  runDetail.value = null
  try {
    runDetail.value = await agentsApi.runDetail(id)
  } catch (err) {
    ui.error('运行详情加载失败', errorMessage(err))
    runDetailOpen.value = false
  }
}

function simulatedMinutes(run: AgentRun): number {
  const value = run.output?.simulated_minutes
  if (typeof value === 'number') return value
  return Math.round(run.duration_ms / 6000) / 10
}

const REASONING_LABEL: Record<string, string> = {
  llm: '模型推理',
  fallback: '降级·确定性',
  deterministic: '确定性',
}

const llmEnabled = computed(() => Boolean(llm.value?.config.enabled))
const detailMeta = computed(() => runLlmMeta(runDetail.value))

function runLlmMeta(run: AgentRun | null | undefined): LlmRunMeta | null {
  const meta = run?.output?.llm as unknown
  return meta && typeof meta === 'object' ? (meta as LlmRunMeta) : null
}

function reasoningTone(kind?: string): string {
  if (kind === 'llm') return 'accent'
  if (kind === 'fallback') return 'warning'
  return 'muted'
}

function phaseTone(phase: string): string {
  if (phase === '感知') return 'blue'
  if (phase === '推理' || phase === '归因') return 'violet'
  if (phase === '决策') return 'accent'
  if (phase === '执行' || phase === '求解') return 'teal'
  return 'muted'
}

function gotoPlan(planId: number) {
  runDetailOpen.value = false
  router.push({ path: '/plans', query: { plan: planId } })
}

onMounted(() => void load())
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="C / M / A ORCHESTRATION · 协同执行"
      title="智能体中心"
      subtitle="化合物级总控、分子级协调与原子级执行的三级智能体编队。所有输出均经硬约束校验，写入基线必须经过审批与电子签名。"
    >
      <template #actions>
        <button class="btn btn-sm" :disabled="loading" @click="load">
          <span v-if="loading" class="spinner" /><AppIcon v-else name="refresh" :size="15" /> 刷新
        </button>
        <button v-if="canRun" class="btn btn-sm btn-primary" @click="openRunModal">
          <AppIcon name="play" :size="15" /> 运行智能体
        </button>
      </template>
      <template #meta>
        <div class="flex items-center gap-10 fs-12 muted wrap">
          <span class="flex items-center gap-6"><span class="dot dot-live" />编队在线</span>
          <span class="hide-mobile">ReAct 全过程可追溯 · 输出只读直至签名</span>
        </div>
      </template>
    </PageHeader>

    <div v-if="error" class="panel inline-error">
      <AppIcon name="warning" :size="17" /> {{ error }}
      <button class="btn btn-sm" @click="load">重试</button>
    </div>

    <section class="agent-stats">
      <div class="astat">
        <span class="astat-icon accent"><AppIcon name="agents" :size="18" /></span>
        <div><strong class="num">{{ catalog?.summary.total || 0 }}</strong><span>编队智能体</span></div>
        <em>{{ catalog?.summary.online || 0 }} 在线</em>
      </div>
      <div class="astat">
        <span class="astat-icon teal"><AppIcon name="play" :size="18" /></span>
        <div><strong class="num">{{ catalog?.summary.total_runs || 0 }}</strong><span>累计运行</span></div>
        <em>全链路留痕</em>
      </div>
      <div class="astat">
        <span class="astat-icon blue"><AppIcon name="check" :size="18" /></span>
        <div><strong class="num">{{ totalSuccess.toFixed(1) }}%</strong><span>平均成功率</span></div>
        <em>近 30 天</em>
      </div>
      <div class="astat">
        <span class="astat-icon violet"><AppIcon name="layers" :size="18" /></span>
        <div><strong class="num">3</strong><span>智能体层级</span></div>
        <em>C / M / A 编队</em>
      </div>
    </section>

    <section class="level-bar">
      <div class="segmented">
        <button v-for="item in levels" :key="item.level" :class="{ active: levelFilter === item.level }" @click="levelFilter = item.level">
          {{ item.label }}
          <span class="seg-count">{{ item.count }}</span>
        </button>
      </div>
      <button v-if="agentFilter" class="chip active" @click="agentFilter = ''">
        <AppIcon name="filter" :size="12" /> {{ activeAgentName }} ×
      </button>
      <div class="level-note">
        <span class="badge badge-accent">C 化合物级</span>
        <span class="badge badge-teal">M 分子级</span>
        <span class="badge badge-blue">A 原子级</span>
      </div>
    </section>

    <section v-if="loading && !catalog" class="agent-grid">
      <div v-for="n in 6" :key="n" class="skeleton" style="height: 240px; border-radius: 14px" />
    </section>

    <section v-else class="agent-grid">
      <article v-for="agent in filteredAgents" :key="agent.code" class="agent-card" :class="{ selected: agentFilter === agent.code }">
        <header class="agent-head">
          <span class="agent-avatar" :class="`lv-${agent.level}`">{{ agent.code }}</span>
          <div class="agent-identity">
            <div class="agent-name">
              {{ agent.name }}
              <span class="badge" :class="`badge-${LEVEL_TONE[agent.level]}`">{{ AGENT_LEVEL_LABEL[agent.level] || agent.level }}</span>
            </div>
            <div class="agent-duty">{{ agent.duty }}</div>
          </div>
          <span class="agent-status" :class="agent.status === 'online' || agent.status === 'active' ? 'online' : 'offline'">
            <span class="dot" />{{ agent.status === 'online' || agent.status === 'active' ? '在线' : agent.status }}
          </span>
        </header>

        <div class="agent-permission">
          <AppIcon name="shield" :size="13" />
          {{ agent.permission }}
        </div>

        <div class="agent-skills">
          <span v-for="skill in agent.skills" :key="skill" class="skill-chip">{{ skill }}</span>
        </div>

        <div class="agent-metrics">
          <div><span>运行次数</span><strong class="num">{{ agent.runs }}</strong></div>
          <div><span>成功率</span><strong class="num" :class="agent.success_rate >= 95 ? 'text-success' : 'text-warning'">{{ agent.success_rate.toFixed(1) }}%</strong></div>
          <div><span>平均耗时</span><strong class="num">{{ agent.avg_minutes.toFixed(1) }}m</strong></div>
        </div>

        <div class="agent-last">
          <div class="agent-last-title">最近运行 · {{ relativeTime(agent.last_run_at) }}</div>
          <p>{{ agent.last_summary || '暂无运行记录' }}</p>
        </div>

        <div class="agent-actions">
          <button class="btn btn-sm btn-ghost" @click="filterByAgent(agent)">
            {{ agentFilter === agent.code ? '取消筛选' : '运行记录' }}
          </button>
          <button v-if="canRun" class="btn btn-sm" @click="openRunModal">
            <AppIcon name="play" :size="12" /> 编排
          </button>
        </div>
      </article>
    </section>

    <section class="grid grid-2-1 runs-section">
      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <span class="title-mark" />运行台账
            <span v-if="agentFilter" class="badge badge-accent">{{ agentFilter }}</span>
          </div>
          <div class="flex items-center gap-8">
            <select v-model="scenarioFilter" class="select select-sm">
              <option value="">全部场景</option>
              <option v-for="(label, key) in RUN_SCENARIO_LABEL" :key="key" :value="key">{{ label }}</option>
            </select>
            <span class="panel-sub">{{ filteredRuns.length }} 条</span>
          </div>
        </div>
        <div class="panel-body flush">
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>运行编号</th>
                  <th>智能体</th>
                  <th>场景</th>
                  <th>摘要</th>
                  <th>操作人</th>
                  <th>开始时间</th>
                  <th>推理</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in filteredRuns" :key="run.id" @click="openRun(run.id)">
                  <td class="cell-strong mono">{{ run.code }}</td>
                  <td>
                    <span class="agent-mini" :class="`lv-${run.level}`">{{ run.agent_code }}</span>
                    <span class="fs-12">{{ run.agent_name }}</span>
                  </td>
                  <td>{{ RUN_SCENARIO_LABEL[run.scenario] || run.scenario }}</td>
                  <td class="run-summary-cell">{{ run.summary }}</td>
                  <td>{{ run.operator }}</td>
                  <td>{{ formatDateTime(run.started_at) }}</td>
                  <td>
                    <span class="badge" :class="`badge-${reasoningTone(runLlmMeta(run)?.mode)}`">
                      {{ runLlmMeta(run)?.mode === 'llm' ? '模型' : '确定性' }}
                    </span>
                  </td>
                  <td><StatusBadge :status="run.status" :label="run.status === 'succeeded' ? '成功' : run.status" /></td>
                  <td class="cell-actions"><button class="btn btn-sm" @click.stop="openRun(run.id)">ReAct</button></td>
                </tr>
                <tr v-if="!filteredRuns.length">
                  <td colspan="9"><div class="empty">{{ loading ? '加载中…' : '暂无运行记录' }}</div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="panel safety-panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />编排安全边界</div>
          <span class="badge badge-success">写保护 active</span>
        </div>
        <div class="panel-body">
          <div class="safety-item">
            <span class="safety-icon accent"><AppIcon name="stamp" :size="16" /></span>
            <div>
              <strong>C 级 · 可写基线</strong>
              <p>必须通过生产指挥部终审 + 电子签名，写保护网关才允许写入 APS/MES。</p>
            </div>
          </div>
          <div class="safety-item">
            <span class="safety-icon teal"><AppIcon name="layers" :size="16" /></span>
            <div>
              <strong>M 级 · 协同建议</strong>
              <p>输出协调建议与候选批次，不得直接修改基线；M-03 开工前缺口硬阻断不可人工放行。</p>
            </div>
          </div>
          <div class="safety-item">
            <span class="safety-icon blue"><AppIcon name="shield" :size="16" /></span>
            <div>
              <strong>A 级 · 只读建议</strong>
              <p>原子级仅输出建议归档，必须经 M/C 级协调或人工采纳后进入排产链路。</p>
            </div>
          </div>
          <div class="safety-foot">
            <AppIcon name="lock" :size="13" />
            LLM 与求解器均无直写权限，所有写入尝试记录哈希审计链。
          </div>
        </div>
      </div>

      <div class="panel brain-panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />编排大脑 · 模型与工具面</div>
          <span class="badge" :class="llmEnabled ? 'badge-accent' : 'badge-muted'">
            {{ llmEnabled ? '内网模型' : '确定性编排' }}
          </span>
        </div>
        <div class="panel-body">
          <div class="brain-row">
            <span>模型</span>
            <strong>{{ llm?.config.model || '未配置' }}</strong>
          </div>
          <div class="brain-row">
            <span>端点</span>
            <strong class="mono truncate">{{ llm?.config.base_url || '—' }}</strong>
          </div>
          <div class="brain-row">
            <span>凭据</span>
            <strong :class="llm?.credential_present ? 'text-success' : 'text-warning'">
              {{ llm?.credential_present ? `${llm.credential_source} 已就绪` : `${llm?.credential_source || 'LISA_LLM_API_KEY'} 未设置` }}
            </strong>
          </div>
          <div class="brain-row">
            <span>近 {{ llm?.runs.window || 20 }} 次运行</span>
            <strong>模型 {{ llm?.runs.llm || 0 }} · 确定性 {{ llm?.runs.fallback || 0 }}</strong>
          </div>
          <p class="brain-note">
            模型只负责推理与选择工具，每个数字都由 LISA 代码实算后回填；内网模型不可用时自动降级为确定性编排，排产链路不中断。密钥只写环境变量名，不落库、不进日志。
          </p>
          <button class="btn btn-sm btn-ghost" :disabled="!mcp" @click="showToolList = !showToolList">
            <AppIcon name="terminal" :size="13" />
            只读工具面 {{ mcp?.count ?? 0 }} 个{{ showToolList ? ' · 收起' : ' · 展开' }}
          </button>
          <div v-if="showToolList && mcp" class="tool-list">
            <div class="tool-endpoint mono">{{ mcp.endpoint }} · JSON-RPC {{ mcp.protocol_version }}</div>
            <div v-for="entry in mcp.tools" :key="entry.name" class="tool-item">
              <code>{{ entry.name }}</code>
              <p>{{ entry.description }}</p>
            </div>
          </div>
          <div v-else-if="mcp" class="tool-count-line">
            {{ mcp.server.name }} v{{ mcp.server.version }} · {{ mcp.read_only ? '全量只读' : '含写操作' }}
          </div>
        </div>
      </div>

      <div class="panel queue-panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />后台任务队列</div>
          <span class="badge" :class="queue?.worker_alive ? 'badge-success' : queue?.worker_enabled ? 'badge-warning' : 'badge-muted'">
            {{ queue?.worker_alive ? 'worker 存活' : queue?.worker_enabled ? 'worker 未存活' : 'worker 已关闭' }}
          </span>
        </div>
        <div class="panel-body">
          <div class="queue-grid">
            <div><span>排队</span><strong class="num">{{ queue?.queued ?? 0 }}</strong></div>
            <div><span>执行中</span><strong class="num">{{ queue?.running ?? 0 }}</strong></div>
            <div>
              <span>最久等待</span>
              <strong class="num">{{ queue?.oldest_queued_seconds != null ? `${queue.oldest_queued_seconds}s` : '—' }}</strong>
            </div>
            <div><span>失联执行</span><strong class="num" :class="{ 'text-warning': (queue?.silent_workers ?? 0) > 0 }">{{ queue?.silent_workers ?? 0 }}</strong></div>
          </div>
          <p v-if="queueWarning" class="queue-warning"><AppIcon name="warning" :size="13" /> {{ queueWarning }}</p>
          <p v-else class="queue-note">
            重排跑在后台 worker 里，HTTP 请求只负责入队；任务状态、耗时与失败原因都留在库里，可在审计里追到发起人。
          </p>
          <div class="queue-kinds">
            <span class="fs-12 muted">已登记任务类型</span>
            <div class="flex gap-6 wrap">
              <span v-for="kind in queue?.kinds || []" :key="kind" class="badge badge-blue mono">{{ kind }}</span>
              <span v-if="!queue?.kinds?.length" class="badge badge-muted">无</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Run modal -->
    <BaseModal v-model="runOpen" title="运行智能体编排" subtitle="选择编排场景，系统将按三级智能体链路执行并全程留痕" width="760px">
      <div class="run-body">
        <div class="scenario-options">
          <button
            v-for="scenario in SCENARIO_OPTIONS"
            :key="scenario.key"
            class="scenario-option"
            :class="[`tone-${scenario.tone}`, { active: runScenario === scenario.key }]"
            @click="runScenario = scenario.key"
          >
            <span class="so-top">
              <span class="so-dot" />
              <strong>{{ scenario.label }}</strong>
              <em>{{ scenario.minutes }}</em>
            </span>
            <span class="so-agent mono">{{ scenario.agent }}</span>
            <span class="so-desc">{{ scenario.desc }}</span>
          </button>
        </div>

        <div v-if="runScenario === 'local'" class="run-fields">
          <label class="field">
            <span class="field-label">目标域</span>
            <select v-model="runDomain" class="select">
              <option v-for="domain in DOMAINS" :key="domain" :value="domain">{{ domain }}域</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">方案场景</span>
            <select v-model="runPlanScenario" class="select">
              <option value="A">A · 交期优先</option>
              <option value="B">B · 瓶颈均衡</option>
              <option value="C">C · 换型成本</option>
            </select>
          </label>
        </div>

        <div v-if="runScenario === 'change'" class="run-fields">
          <label class="field">
            <span class="field-label">扰动事件</span>
            <select v-model="runChangeId" class="select">
              <option :value="null">请选择未关闭的扰动事件</option>
              <option v-for="change in openChanges" :key="change.id" :value="change.id">
                {{ change.code }} · {{ change.title }}（{{ change.status }}）
              </option>
            </select>
          </label>
        </div>

        <div class="run-shield">
          <AppIcon name="shield" :size="16" />
          <div>
            <strong>人机协同护栏</strong>
            <p>
              {{ currentScenarioMeta?.label }} 由 {{ currentScenarioMeta?.agent }} 执行，预计 {{ currentScenarioMeta?.minutes }}。
              输出为建议或待审批方案，不会直接写入生产基线。
            </p>
          </div>
        </div>

        <div v-if="runError" class="run-error"><AppIcon name="warning" :size="14" /> {{ runError }}</div>

        <div v-if="activeJob" class="run-queue">
          <div class="rq-head">
            <span class="spinner" />
            <strong>任务 #{{ activeJob.id }}</strong>
            <span class="mono">{{ activeJob.kind }}</span>
            <em>{{ jobStatusText(activeJob) }}</em>
          </div>
          <div class="rq-bar"><span :style="{ width: `${Math.max(4, activeJob.progress)}%` }" /></div>
          <p class="rq-note">
            编排已交给后台 worker，关掉本页不影响执行；排队与执行过程都落在 jobs 表里，进程重启后未跑完的任务会被重新领取。
          </p>
        </div>
      </div>

      <template #footer>
        <button v-if="running && activeJob?.status === 'queued' && canCancelJob" class="btn btn-ghost" @click="cancelJob">
          取消排队
        </button>
        <button v-else class="btn btn-ghost" :disabled="running" @click="runOpen = false">
          {{ running ? '执行中…' : '关闭' }}
        </button>
        <button class="btn btn-primary" :disabled="running" @click="startRun">
          <span v-if="running" class="spinner" />
          <AppIcon v-else name="play" :size="15" />
          {{ running ? (activeJob ? '已入队，等待 worker' : '提交中…') : '启动编排' }}
        </button>
      </template>
    </BaseModal>

    <!-- Run detail -->
    <BaseDrawer v-model="runDetailOpen" width="760px" title="ReAct 运行追溯" subtitle="Thought → Action → Observation 全链路留痕">
      <div v-if="!runDetail" class="detail-loading"><span class="spinner" /> 加载运行记录…</div>
      <template v-else>
        <div class="run-detail-head">
          <div>
            <div class="rd-code mono">{{ runDetail.code }}</div>
            <div class="rd-title">
              {{ runDetail.agent_name }}
              <span class="badge" :class="`badge-${LEVEL_TONE[runDetail.level]}`">{{ runDetail.level }}</span>
              <StatusBadge :status="runDetail.status" :label="runDetail.status === 'succeeded' ? '成功' : runDetail.status" />
            </div>
            <div class="rd-meta">
              <span>{{ RUN_SCENARIO_LABEL[runDetail.scenario] || runDetail.scenario }}</span>
              <span>{{ runDetail.operator }}</span>
              <span>{{ formatDateTime(runDetail.started_at) }}</span>
            </div>
          </div>
          <div class="rd-timer">
            <span>模拟耗时</span>
            <strong class="num">{{ simulatedMinutes(runDetail) }}<em>min</em></strong>
            <em>{{ (runDetail.duration_ms / 1000).toFixed(1) }}s 实际</em>
          </div>
        </div>

        <div class="rd-summary">{{ runDetail.summary }}</div>

        <div v-if="detailMeta" class="rd-brain" :class="detailMeta.mode === 'llm' ? 'is-llm' : 'is-fallback'">
          <div class="rb-head">
            <AppIcon :name="detailMeta.mode === 'llm' ? 'agents' : 'shield'" :size="14" />
            <strong>{{ detailMeta.mode === 'llm' ? '内网模型推理' : '确定性编排（模型未参与）' }}</strong>
            <span class="rb-chip mono">{{ detailMeta.model || '—' }}</span>
          </div>
          <div class="rb-grid">
            <div><span>调用次数</span><strong class="num">{{ detailMeta.calls }}</strong></div>
            <div><span>输入 token</span><strong class="num">{{ detailMeta.prompt_tokens }}</strong></div>
            <div><span>输出 token</span><strong class="num">{{ detailMeta.completion_tokens }}</strong></div>
            <div><span>取数工具</span><strong class="num">{{ (runDetail.steps || []).filter((s) => s.tool).length }}</strong></div>
          </div>
          <p v-if="detailMeta.reason" class="rb-reason">{{ detailMeta.reason }}</p>
          <p v-if="detailMeta.error" class="rb-error">{{ detailMeta.error.code }} · {{ detailMeta.error.message }}</p>
        </div>

        <div class="rd-steps">
          <div v-for="step in runDetail.steps || []" :key="step.index" class="rd-step">
            <div class="step-rail">
              <span class="step-index">{{ step.index }}</span>
              <span class="step-line" />
            </div>
            <div class="step-body">
              <div class="step-top">
                <span class="badge" :class="`badge-${phaseTone(step.phase)}`">{{ step.phase }}</span>
                <span v-if="step.reasoning" class="badge" :class="`badge-${reasoningTone(step.reasoning)}`">
                  {{ REASONING_LABEL[step.reasoning] || step.reasoning }}
                </span>
                <strong>{{ step.title }}</strong>
                <span class="step-duration num">{{ (step.duration_ms / 1000).toFixed(1) }}s</span>
              </div>
              <p class="step-thought">{{ step.thought }}</p>
              <div class="step-action mono">{{ step.action }}</div>
              <div v-if="step.tool" class="step-tool mono">
                <AppIcon name="terminal" :size="11" />
                <span>{{ step.tool.tool }}</span>
                <em v-if="step.tool.error" class="text-warning">{{ step.tool.error }}</em>
                <em v-else class="num">{{ step.tool.ms }}ms · {{ step.tool.chars }} 字实算数据</em>
              </div>
              <div class="step-observation"><AppIcon name="eye" :size="12" /> {{ step.observation }}</div>
            </div>
          </div>
        </div>

        <div v-if="runDetail.plans?.length" class="rd-plans">
          <div class="section-title" style="display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 650; margin-bottom: 8px; color: var(--text-2)">
            <AppIcon name="approval" :size="14" /> 产出方案
          </div>
          <div class="rd-plan-list">
            <button v-for="plan in runDetail.plans" :key="plan.id" class="rd-plan" @click="gotoPlan(plan.id)">
              <span class="scenario-pill" :class="`scenario-${plan.scenario}`">{{ plan.scenario }}</span>
              <div>
                <strong>{{ plan.code }}</strong>
                <span>{{ SCENARIO_LABEL[plan.scenario] }} · {{ plan.status_label }}</span>
              </div>
              <em class="num">{{ (plan.kpi?.total_score || 0).toFixed(1) }}</em>
              <AppIcon name="chevrons" :size="14" />
            </button>
          </div>
        </div>

        <div class="rd-output">
          <div class="section-title" style="display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 650; margin-bottom: 8px; color: var(--text-2)">
            <AppIcon name="terminal" :size="14" /> 结构化输出
          </div>
          <pre class="code-block">{{ JSON.stringify(runDetail.output, null, 2) }}</pre>
        </div>

        <div class="rd-shield">
          <AppIcon name="shield" :size="14" />
          本次运行未直接写入 APS/MES。任何基线变更必须进入方案审批并完成电子签名。
        </div>
      </template>
    </BaseDrawer>
  </div>
</template>

<style scoped>
.inline-error { display: flex; align-items: center; gap: 9px; padding: 11px 15px; margin-bottom: 14px; color: var(--danger); }
.inline-error .btn { margin-left: auto; }

.agent-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.astat {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 15px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  position: relative;
}
.astat-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex: none;
}
.astat-icon.accent { background: var(--accent-soft); color: var(--accent); }
.astat-icon.teal { background: var(--teal-soft); color: var(--teal); }
.astat-icon.blue { background: var(--blue-soft); color: var(--blue); }
.astat-icon.violet { background: var(--violet-soft); color: var(--violet); }
.astat strong { display: block; font-size: 22px; line-height: 1.1; }
.astat span { font-size: 11px; color: var(--text-3); }
.astat em { position: absolute; right: 14px; top: 14px; font-style: normal; font-size: 10px; color: var(--text-3); }

.level-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.seg-count {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 15px;
  padding: 0 4px;
  margin-left: 4px;
  border-radius: 99px;
  background: var(--panel-inset);
  font-size: 9px;
  color: var(--text-3);
}
.segmented button.active .seg-count { background: var(--accent-soft); color: var(--accent); }
.level-note { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }

.agent-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 11px;
  padding: 15px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  transition: border-color 0.18s ease, transform 0.18s ease;
  position: relative;
  overflow: hidden;
}
.agent-card:hover { border-color: var(--border-accent); transform: translateY(-2px); }
.agent-card.selected { border-color: var(--accent-line); box-shadow: 0 0 0 1px var(--accent-line), var(--shadow-soft); }
.agent-head { display: flex; align-items: flex-start; gap: 10px; }
.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: -0.02em;
  flex: none;
  border: 1px solid transparent;
}
.lv-C { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-line); }
.lv-M { color: var(--teal); background: var(--teal-soft); border-color: color-mix(in srgb, var(--teal) 30%, transparent); }
.lv-A { color: var(--blue); background: var(--blue-soft); border-color: color-mix(in srgb, var(--blue) 30%, transparent); }
.agent-identity { flex: 1; min-width: 0; }
.agent-name { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 650; flex-wrap: wrap; }
.agent-duty {
  margin-top: 3px;
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-3);
  flex: none;
}
.agent-status .dot { background: var(--text-3); }
.agent-status.online { color: var(--success); }
.agent-status.online .dot { background: var(--success); box-shadow: 0 0 0 3px var(--success-soft); }
.agent-permission {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 9px;
  border-radius: 7px;
  background: var(--panel-inset);
  border: 1px solid var(--border);
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.45;
}
.agent-permission :deep(svg) { flex: none; margin-top: 1px; color: var(--teal); }
.agent-skills { display: flex; flex-wrap: wrap; gap: 4px; }
.skill-chip {
  font-size: 9.5px;
  padding: 2px 7px;
  border-radius: 99px;
  border: 1px solid var(--border);
  color: var(--text-3);
  background: var(--panel-inset);
}
.agent-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 5px;
  padding-top: 9px;
  border-top: 1px dashed var(--border);
}
.agent-metrics span { display: block; font-size: 9.5px; color: var(--text-3); }
.agent-metrics strong { font-size: 12.5px; }
.agent-last p {
  font-size: 10.5px;
  color: var(--text-2);
  line-height: 1.5;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 31px;
}
.agent-last-title { font-size: 9.5px; color: var(--text-3); }
.agent-actions { display: flex; gap: 6px; margin-top: auto; }
.agent-actions .btn { flex: 1; }

.agent-mini {
  display: inline-grid;
  place-items: center;
  min-width: 34px;
  height: 19px;
  padding: 0 4px;
  margin-right: 6px;
  border-radius: 5px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 700;
}
.run-summary-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-sm { min-height: 30px; font-size: 11.5px; padding: 4px 30px 4px 9px; width: 120px; }
.data-table tbody tr { cursor: pointer; }

.safety-panel .panel-body { display: flex; flex-direction: column; gap: 12px; }
.safety-item { display: flex; gap: 10px; align-items: flex-start; }
.safety-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex: none;
}
.safety-icon.accent { background: var(--accent-soft); color: var(--accent); }
.safety-icon.teal { background: var(--teal-soft); color: var(--teal); }
.safety-icon.blue { background: var(--blue-soft); color: var(--blue); }
.safety-item strong { font-size: 12px; }
.safety-item p { font-size: 10.5px; color: var(--text-3); line-height: 1.55; margin-top: 2px; }
.safety-foot {
  margin-top: auto;
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

/* 编排大脑：模型接入状态 + 只读工具面 */
.brain-panel .panel-body { display: flex; flex-direction: column; gap: 9px; }
.brain-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  font-size: 11px;
  color: var(--text-3);
}
.brain-row strong { color: var(--text-1); font-weight: 600; }
.brain-row .truncate {
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
}
.brain-note {
  margin: 0;
  padding: 9px 11px;
  border-radius: 7px;
  background: var(--panel-inset);
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-3);
}
.tool-endpoint {
  font-size: 10px;
  color: var(--text-3);
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.tool-list { display: flex; flex-direction: column; gap: 8px; max-height: 280px; overflow: auto; }
.tool-item code {
  font-size: 10.5px;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 1px 6px;
  border-radius: 4px;
}
.tool-item p { margin: 3px 0 0; font-size: 10.5px; line-height: 1.55; color: var(--text-3); }
.tool-count-line { font-size: 10px; color: var(--text-3); }

/* run modal */
.run-body { display: flex; flex-direction: column; gap: 14px; }
.scenario-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.scenario-option {
  text-align: left;
  padding: 11px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.16s ease;
  color: var(--text-2);
}
.scenario-option:hover { border-color: var(--border-strong); }
.scenario-option.active { border-color: var(--accent-line); background: var(--accent-soft); box-shadow: 0 0 0 1px var(--accent-line); }
.so-top { display: flex; align-items: center; gap: 6px; }
.so-top strong { font-size: 12px; color: var(--text); }
.so-top em { margin-left: auto; font-style: normal; font-size: 9.5px; color: var(--text-3); }
.so-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex: none; }
.tone-teal .so-dot { background: var(--teal); }
.tone-blue .so-dot { background: var(--blue); }
.tone-violet .so-dot { background: var(--violet); }
.tone-warning .so-dot { background: var(--warning); }
.so-agent { font-size: 9px; color: var(--text-3); }
.so-desc { font-size: 10px; color: var(--text-3); line-height: 1.45; }
.run-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.run-shield {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid var(--teal-soft);
  background: var(--teal-soft);
  color: var(--teal);
}
.run-shield strong { font-size: 11.5px; display: block; }
.run-shield p { font-size: 10.5px; color: var(--text-2); line-height: 1.55; margin-top: 2px; }
.run-error {
  display: flex;
  gap: 7px;
  padding: 9px 11px;
  border-radius: 7px;
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  color: var(--danger);
  font-size: 11.5px;
}

/* 后台任务：入队后的进度条 */
.run-queue {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
}
.rq-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-1); }
.rq-head .mono { font-size: 10.5px; color: var(--text-3); }
.rq-head em { margin-left: auto; font-style: normal; font-size: 10.5px; color: var(--accent); }
.rq-bar { height: 4px; border-radius: 99px; background: var(--panel-inset); overflow: hidden; }
.rq-bar span { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width 0.5s ease; }
.rq-note { margin: 0; font-size: 10.5px; line-height: 1.55; color: var(--text-3); }

/* 队列体检面板 */
.queue-panel .panel-body { display: flex; flex-direction: column; gap: 10px; }
.queue-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.queue-grid div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 9px;
  border-radius: 8px;
  background: var(--panel-inset);
  border: 1px solid var(--border);
}
.queue-grid span { font-size: 9.5px; color: var(--text-3); }
.queue-grid strong { font-size: 16px; }
.queue-note, .queue-warning { margin: 0; font-size: 10.5px; line-height: 1.6; color: var(--text-3); }
.queue-warning {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 8px 10px;
  border-radius: 7px;
  background: var(--warning-soft);
  color: var(--warning);
}
.queue-kinds { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; border-top: 1px dashed var(--border); }
.wrap { flex-wrap: wrap; }

/* run detail */
.detail-loading { display: flex; align-items: center; justify-content: center; gap: 9px; padding: 50px 0; color: var(--text-3); font-size: 12px; }
.run-detail-head { display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
.rd-code { font-size: 10.5px; color: var(--text-3); }
.rd-title { display: flex; align-items: center; gap: 7px; font-size: 16px; font-weight: 700; margin-top: 3px; flex-wrap: wrap; }
.rd-meta { display: flex; flex-wrap: wrap; gap: 10px; font-size: 10.5px; color: var(--text-3); margin-top: 4px; }
.rd-timer { text-align: right; }
.rd-timer span { display: block; font-size: 10px; color: var(--text-3); }
.rd-timer strong { font-size: 22px; color: var(--accent); }
.rd-timer strong em { font-style: normal; font-size: 11px; margin-left: 2px; color: var(--text-3); }
.rd-timer > em { display: block; font-style: normal; font-size: 9.5px; color: var(--text-3); }
.rd-summary {
  margin: 13px 0 16px;
  padding: 11px 13px;
  border-radius: 9px;
  border-left: 3px solid var(--accent);
  background: var(--panel-inset);
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.6;
}
.rd-brain {
  margin: -4px 0 16px;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.rd-brain.is-llm { border-color: var(--accent-line); }
.rb-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-1); }
.rb-head strong { font-weight: 650; }
.rb-chip {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--text-3);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 1px 7px;
}
.rb-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.rb-grid div { display: flex; flex-direction: column; gap: 2px; }
.rb-grid span { font-size: 10px; color: var(--text-3); }
.rb-grid strong { font-size: 13px; color: var(--text-1); }
.rb-reason, .rb-error { margin: 0; font-size: 10.5px; line-height: 1.55; color: var(--text-3); }
.rb-error { color: var(--warning); }
.rd-steps { display: flex; flex-direction: column; }
.rd-step { display: flex; gap: 11px; }
.step-rail { display: flex; flex-direction: column; align-items: center; width: 24px; flex: none; }
.step-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--panel-strong);
  border: 1px solid var(--border-strong);
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--accent);
  flex: none;
}
.step-line { flex: 1; width: 1px; background: var(--border-strong); min-height: 14px; }
.rd-step:last-child .step-line { display: none; }
.step-body { flex: 1; min-width: 0; padding-bottom: 16px; }
.step-top { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.step-top strong { font-size: 12px; }
.step-duration { margin-left: auto; font-size: 9.5px; color: var(--text-3); }
.step-thought { font-size: 11.5px; color: var(--text-2); line-height: 1.6; margin-top: 5px; }
.step-action {
  margin-top: 6px;
  padding: 5px 9px;
  border-radius: 6px;
  background: var(--panel-inset);
  border: 1px solid var(--border);
  font-size: 10px;
  color: var(--teal);
  overflow-x: auto;
  white-space: nowrap;
}
.step-observation {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: 6px;
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.5;
}
.step-observation :deep(svg) { flex: none; margin-top: 1px; }
.step-tool {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  padding: 5px 9px;
  border-radius: 6px;
  background: var(--accent-soft);
  font-size: 10.5px;
  color: var(--text-2);
}
.step-tool em { font-style: normal; margin-left: auto; color: var(--text-3); font-size: 10px; }
.rd-plans { margin-top: 6px; }
.rd-plan-list { display: flex; flex-direction: column; gap: 6px; }
.rd-plan {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  text-align: left;
  color: var(--text);
  transition: border-color 0.16s ease;
}
.rd-plan:hover { border-color: var(--border-accent); }
.rd-plan > div { flex: 1; min-width: 0; }
.rd-plan strong { display: block; font-size: 11.5px; font-family: var(--mono); }
.rd-plan span { font-size: 10px; color: var(--text-3); }
.rd-plan em { font-style: normal; font-size: 14px; color: var(--accent); }
.scenario-pill {
  width: 28px;
  height: 28px;
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
.scenario-C { color: var(--violet); background: var(--violet-soft); border: 1px solid color-mix(in srgb, var(--violet) 30%, transparent); }
.rd-output { margin-top: 16px; }
.rd-output .code-block { max-height: 260px; }
.rd-shield {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  margin-top: 14px;
  padding: 9px 11px;
  border-radius: 7px;
  border: 1px dashed var(--border-strong);
  font-size: 10px;
  color: var(--text-3);
  line-height: 1.5;
}

@media (max-width: 1279px) {
  .agent-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1023px) {
  .agent-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 767px) {
  .agent-grid { grid-template-columns: 1fr; gap: 10px; }
  .agent-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .astat { padding: 11px; }
  .astat strong { font-size: 19px; }
  .astat em { display: none; }
  .level-note { width: 100%; margin-left: 0; }
  .scenario-options { grid-template-columns: 1fr; }
  .run-fields { grid-template-columns: 1fr; }
  .rd-summary { font-size: 11.5px; }
}
</style>
