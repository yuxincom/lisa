<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { agentsApi, systemApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type {
  BackupOverview,
  ClearanceConfig,
  LlmConfig,
  LlmStatus,
  LlmTestResult,
  MetaInfo,
  PlantConfig,
  ScenarioMeta,
  SecurityInfo,
  SettingsValues,
  User,
} from '@/types'
import { formatNumber, shortRole } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'

type Tab = 'params' | 'llm' | 'security' | 'users' | 'system'
type SystemStats = Awaited<ReturnType<typeof systemApi.stats>>

const WEIGHT_LABELS: Record<string, string> = {
  delivery: '交期优先',
  bottleneck: '瓶颈均衡',
  changeover: '换型成本',
  cost: '综合成本',
}
const THRESHOLD_LABELS: Record<string, string> = {
  data_quality: '数据质量阈值',
  confidence: '置信度阈值',
  kit: '齐套率目标',
}

const auth = useAuthStore()
const ui = useUiStore()

const tab = ref<Tab>('params')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const form = ref<SettingsValues | null>(null)
const scenarios = ref<Record<string, ScenarioMeta>>({})
const security = ref<SecurityInfo | null>(null)
const users = ref<User[]>([])
const meta = ref<MetaInfo | null>(null)
const stats = ref<SystemStats | null>(null)
const shieldTesting = ref(false)
const exporting = ref('')
const backups = ref<BackupOverview | null>(null)
const backupBusy = ref(false)
const verifying = ref('')

const LLM_KEYS: (keyof LlmConfig)[] = [
  'enabled', 'base_url', 'model', 'api_key_env', 'timeout_seconds', 'max_steps',
  'temperature', 'internal_only', 'internal_suffixes', 'redact_fields', 'max_observation_chars',
]

const llm = ref<LlmStatus | null>(null)
const llmForm = ref<LlmConfig | null>(null)
const llmSaving = ref(false)
const llmTesting = ref(false)
const llmResult = ref<LlmTestResult | null>(null)
const llmError = ref('')

const weightSum = computed(() => {
  if (!form.value) return 0
  return Object.values(form.value.weights || {}).reduce((sum, value) => sum + Number(value || 0), 0)
})
const weightBalanced = computed(() => Math.abs(weightSum.value - 1) < 0.011)
const canEdit = computed(() => auth.isAdmin)
const scenarioList = computed(() => Object.entries(scenarios.value))

const statTiles = computed(() => [
  { label: '订单', value: stats.value?.orders },
  { label: '工序', value: stats.value?.operations },
  { label: '资源', value: stats.value?.resources },
  { label: '方案', value: stats.value?.plans },
  { label: '规则', value: stats.value?.rules },
  { label: '智能体运行', value: stats.value?.agent_runs },
  { label: '告警', value: stats.value?.alerts },
  { label: '审计记录', value: stats.value?.audit_logs },
])

const dbEngineLabel = computed(() => {
  const engine = stats.value?.db_engine || backups.value?.dialect || ''
  if (engine === 'sqlite') return 'SQLite'
  if (engine === 'postgresql') return 'PostgreSQL'
  return engine || '—'
})

const tabs = computed(() => [
  { key: 'params' as Tab, label: '排产参数' },
  { key: 'llm' as Tab, label: '模型编排' },
  { key: 'security' as Tab, label: '安全合规' },
  { key: 'users' as Tab, label: '用户与角色', count: users.value.length },
  { key: 'system' as Tab, label: '系统信息' },
])

const llmSuffixText = computed({
  get: () => (llmForm.value?.internal_suffixes || []).join(', '),
  set: (value: string) => {
    if (llmForm.value) llmForm.value.internal_suffixes = splitList(value)
  },
})
const llmRedactText = computed({
  get: () => (llmForm.value?.redact_fields || []).join(', '),
  set: (value: string) => {
    if (llmForm.value) llmForm.value.redact_fields = splitList(value)
  },
})

function splitList(value: string): string[] {
  return value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean)
}

function llmPayload(): Partial<LlmConfig> {
  if (!llmForm.value) return {}
  const source = llmForm.value as unknown as Record<string, unknown>
  const picked: Record<string, unknown> = {}
  LLM_KEYS.forEach((key) => {
    picked[key] = source[key]
  })
  picked.timeout_seconds = Number(picked.timeout_seconds)
  picked.max_steps = Number(picked.max_steps)
  picked.temperature = Number(picked.temperature)
  picked.max_observation_chars = Number(picked.max_observation_chars)
  return picked as Partial<LlmConfig>
}

function weightTone(value: number) {
  return value >= 0.35 ? 'var(--accent)' : value >= 0.2 ? 'var(--teal)' : 'var(--blue)'
}

async function loadLlm() {
  try {
    const status = await agentsApi.llm()
    llm.value = status
    llmForm.value = JSON.parse(JSON.stringify(status.config)) as LlmConfig
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function saveLlm() {
  if (!canEdit.value) return
  llmSaving.value = true
  llmError.value = ''
  try {
    const res = await agentsApi.saveLlm(llmPayload())
    if (llm.value) llm.value.config = res.config
    llmForm.value = JSON.parse(JSON.stringify(res.config)) as LlmConfig
    llm.value = llm.value ? { ...llm.value, credential_present: res.credential_present } : llm.value
    ui.success('模型编排配置已保存', res.config.enabled ? `启用后 ReAct 阶段由 ${res.config.model} 推理` : '当前为确定性编排')
  } catch (err) {
    llmError.value = errorMessage(err)
    ui.error('保存失败', llmError.value)
  } finally {
    llmSaving.value = false
  }
}

async function testLlm() {
  llmTesting.value = true
  llmError.value = ''
  llmResult.value = null
  try {
    llmResult.value = await agentsApi.testLlm(llmPayload())
    ui.success('内网模型连通', `${llmResult.value.model} · ${llmResult.value.latency_ms}ms`)
  } catch (err) {
    llmError.value = errorMessage(err)
    ui.error('连接失败', llmError.value)
  } finally {
    llmTesting.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [settingsRes, securityRes, usersRes, metaRes, statsRes] = await Promise.all([
      systemApi.settings(),
      systemApi.security(),
      systemApi.users(),
      systemApi.meta(),
      systemApi.stats(),
    ])
    form.value = structuredClone(settingsRes.values)
    scenarios.value = settingsRes.scenarios || {}
    security.value = securityRes
    syncClearanceForm()
    syncPlantForm()
    users.value = usersRes.items || []
    meta.value = metaRes
    stats.value = statsRes
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
  void loadLlm()
  void loadBackups()
}

async function loadBackups() {
  if (!canEdit.value) {
    backups.value = null
    return
  }
  try {
    backups.value = await systemApi.backups()
  } catch {
    // 备份目录不可写时后端会报错，这里不让它拖垮整个设置页
    backups.value = null
  }
}

async function runBackup() {
  if (!canEdit.value || backupBusy.value) return
  backupBusy.value = true
  try {
    const res = await systemApi.createBackup()
    ui.success(
      '整库快照已生成',
      `${formatNumber(res.total_rows)} 行 · ${res.file}${res.pruned.length ? ` · 清理旧快照 ${res.pruned.length} 份` : ''}`,
    )
    await loadBackups()
  } catch (err) {
    ui.error('快照失败', errorMessage(err))
  } finally {
    backupBusy.value = false
  }
}

async function checkBackup(name: string) {
  if (verifying.value) return
  verifying.value = name
  try {
    const res = await systemApi.verifyBackup(name)
    ui.success('校验通过', `${res.file} · ${formatNumber(res.total_rows || 0)} 行 · 摘要 ${String(res.payload_digest || '').slice(0, 12)}`)
  } catch (err) {
    ui.error('校验未通过', errorMessage(err))
  } finally {
    verifying.value = ''
  }
}

function reset() {
  systemApi.settings().then((res) => {
    form.value = structuredClone(res.values)
    ui.info('已恢复为当前生效参数')
  }).catch((err) => ui.error('读取参数失败', errorMessage(err)))
}

async function save() {
  if (!form.value || !canEdit.value) return
  saving.value = true
  try {
    const payload: SettingsValues = {
      weights: { ...form.value.weights },
      thresholds: { ...form.value.thresholds },
      freeze_days: Number(form.value.freeze_days),
      shift: { ...form.value.shift },
      approval_timeout_minutes: Number(form.value.approval_timeout_minutes),
      solver_timeout_seconds: Number(form.value.solver_timeout_seconds),
      auto_escalate: Boolean(form.value.auto_escalate),
      write_shield: Boolean(form.value.write_shield),
    }
    const res = await systemApi.updateSettings(payload)
    form.value = structuredClone(res.values)
    ui.success('参数已保存', `已更新 ${res.updated.length} 项配置`)
  } catch (err) {
    ui.error('保存失败', errorMessage(err))
  } finally {
    saving.value = false
  }
}

const clearanceForm = ref<ClearanceConfig | null>(null)
const clearanceSaving = ref(false)
const newLevel = ref('')

function syncClearanceForm() {
  const report = security.value?.clearance
  if (!report) {
    clearanceForm.value = null
    return
  }
  clearanceForm.value = {
    enabled: report.enabled,
    levels: [...report.levels],
    data_default: report.data_default,
    report_hidden: report.report_hidden,
  }
}

function moveLevel(index: number, delta: number) {
  const levels = clearanceForm.value?.levels
  if (!levels) return
  const target = index + delta
  if (target < 0 || target >= levels.length) return
  const next = [...levels]
  const temp = next[index]
  next[index] = next[target]
  next[target] = temp
  clearanceForm.value!.levels = next
}

function addLevel() {
  const name = newLevel.value.trim()
  if (!name || !clearanceForm.value) return
  if (clearanceForm.value.levels.includes(name)) {
    ui.warning('等级重名', `「${name}」已经在等级表里`)
    return
  }
  clearanceForm.value.levels = [...clearanceForm.value.levels, name]
  newLevel.value = ''
}

function removeLevel(index: number) {
  const form = clearanceForm.value
  if (!form || form.levels.length <= 2) return
  const removed = form.levels[index]
  form.levels = form.levels.filter((_, position) => position !== index)
  if (form.data_default === removed) form.data_default = form.levels[0]
}

const clearanceErrors = computed(() => {
  const form = clearanceForm.value
  if (!form) return []
  const issues: string[] = []
  const levels = form.levels.map((item) => item.trim())
  if (levels.some((item) => !item)) issues.push('等级名不能为空')
  if (new Set(levels).size !== levels.length) issues.push('等级名不能重复')
  if (levels.length < 2) issues.push('至少保留 2 个等级')
  if (!levels.includes(form.data_default.trim())) issues.push(`未标注数据的默认密级「${form.data_default}」已不在等级表里`)
  return issues
})

const clearanceOrphans = computed(() => security.value?.clearance?.orders_outside_levels || {})
const orphanCount = computed(() => Object.values(clearanceOrphans.value).reduce((sum, value) => sum + value, 0))

async function saveClearance() {
  const form = clearanceForm.value
  if (!form || !canEdit.value || clearanceErrors.value.length) return
  clearanceSaving.value = true
  try {
    const payload: ClearanceConfig = {
      enabled: form.enabled,
      levels: form.levels.map((item) => item.trim()),
      data_default: form.data_default.trim(),
      report_hidden: form.report_hidden,
    }
    await systemApi.updateSettings({ clearance: payload })
    security.value = await systemApi.security()
    syncClearanceForm()
    syncPlantForm()
    ui.success(
      '密级策略已生效',
      payload.enabled ? `${payload.levels.join(' < ')}，未标注按「${payload.data_default}」` : '密级过滤已关闭：所有账号可见全量数据',
    )
  } catch (err) {
    ui.error('保存失败', errorMessage(err))
  } finally {
    clearanceSaving.value = false
  }
}

const plantForm = ref<PlantConfig | null>(null)
const plantSaving = ref(false)
const newPlant = ref('')
const scopeDraft = ref<Record<string, string[]>>({})

const plantPeople = computed(() => security.value?.plants?.people || [])

function syncPlantForm() {
  const report = security.value?.plants
  if (!report) {
    plantForm.value = null
    scopeDraft.value = {}
    return
  }
  plantForm.value = { enabled: report.enabled, names: [...report.names], data_default: report.data_default }
  scopeDraft.value = Object.fromEntries(report.people.map((person) => [person.username, [...person.plants]]))
}

function addPlant() {
  const name = newPlant.value.trim()
  if (!name || !plantForm.value) return
  if (plantForm.value.names.includes(name)) {
    ui.warning('厂区重名', `「${name}」已经在厂区清单里`)
    return
  }
  plantForm.value.names = [...plantForm.value.names, name]
  newPlant.value = ''
}

function removePlant(index: number) {
  const form = plantForm.value
  if (!form || form.names.length <= 1) return
  const removed = form.names[index]
  form.names = form.names.filter((_, position) => position !== index)
  if (form.data_default === removed) form.data_default = form.names[0]
}

const plantErrors = computed(() => {
  const form = plantForm.value
  if (!form) return []
  const issues: string[] = []
  const names = form.names.map((item) => item.trim())
  if (names.some((item) => !item)) issues.push('厂区名不能为空')
  if (new Set(names).size !== names.length) issues.push('厂区名不能重复')
  if (!names.includes(form.data_default.trim())) issues.push(`未标注数据的默认厂区「${form.data_default}」已不在清单里`)
  return issues
})

const orphanPlants = computed(() => security.value?.plants?.orders_outside_plants || {})
const orphanPlantCount = computed(() => Object.values(orphanPlants.value).reduce((sum, value) => sum + value, 0))
const unknownClaimed = computed(() => security.value?.plants?.unknown_claimed_plants || [])

async function savePlants() {
  const form = plantForm.value
  if (!form || !canEdit.value || plantErrors.value.length) return
  plantSaving.value = true
  try {
    const payload: PlantConfig = {
      enabled: form.enabled,
      names: form.names.map((item) => item.trim()),
      data_default: form.data_default.trim(),
    }
    await systemApi.updateSettings({ plants: payload })
    security.value = await systemApi.security()
    syncPlantForm()
    ui.success(
      '厂区范围已生效',
      payload.enabled
        ? `${payload.names.join(' / ')}，未标注按「${payload.data_default}」；勾了厂区的账号只看这些厂区`
        : '厂区过滤已关闭：所有账号可见全厂数据',
    )
  } catch (err) {
    ui.error('保存失败', errorMessage(err))
  } finally {
    plantSaving.value = false
  }
}

function togglePlantScope(username: string, plant: string) {
  const current = scopeDraft.value[username] || []
  const next = current.includes(plant) ? current.filter((item) => item !== plant) : [...current, plant]
  scopeDraft.value = { ...scopeDraft.value, [username]: next }
}

async function saveScope(username: string) {
  if (!canEdit.value) return
  try {
    await systemApi.updateUserScope(username, { plants: scopeDraft.value[username] || [] })
    security.value = await systemApi.security()
    syncPlantForm()
    const picked = (scopeDraft.value[username] || []).join('、')
    ui.success(`${username} 的厂区范围已更新`, picked || '未勾选厂区 = 不受厂区限制，可见全厂数据')
  } catch (err) {
    ui.error('范围保存失败', errorMessage(err))
  }
}

async function testShield() {
  shieldTesting.value = true
  try {
    const res = await systemApi.writeShieldTest()
    security.value = await systemApi.security()
    syncClearanceForm()
    syncPlantForm()
    if (res.blocked) ui.success('写保护拦截成功', res.message)
    else ui.warning('写保护未拦截', res.message)
  } catch (err) {
    ui.error('演练失败', errorMessage(err))
  } finally {
    shieldTesting.value = false
  }
}

async function exportFile(kind: 'orders' | 'audit') {
  exporting.value = kind
  try {
    if (kind === 'orders') await systemApi.exportOrders()
    else await systemApi.exportAudit()
    ui.success('导出已生成', 'CSV 文件已开始下载')
  } catch (err) {
    ui.error('导出失败', errorMessage(err))
  } finally {
    exporting.value = ''
  }
}

function switchTab(key: Tab) {
  tab.value = key
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L6 · 平台治理"
      title="系统设置"
      subtitle="排产目标权重 · 安全合规策略 · 角色权限矩阵 · 运行环境信息"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button
          v-if="tab === 'params' && canEdit"
          class="btn btn-primary"
          type="button"
          :disabled="saving || !form"
          @click="save"
        >
          <span v-if="saving" class="spinner" />
          <AppIcon v-else name="signature" :size="15" />
          {{ saving ? '保存中…' : '保存参数' }}
        </button>
      </template>
      <template #meta>
        <span>{{ meta?.name_en }} v{{ meta?.version }}</span>
        <span class="meta-dot" />
        <span>环境 <strong class="text-accent">{{ meta?.environment }}</strong></span>
      </template>
    </PageHeader>

    <div class="tabs-row">
      <div class="segmented">
        <button
          v-for="item in tabs"
          :key="item.key"
          type="button"
          :class="{ active: tab === item.key }"
          @click="switchTab(item.key)"
        >
          {{ item.label }}<span v-if="item.count" class="tab-count">{{ item.count }}</span>
        </button>
      </div>
      <span v-if="!canEdit" class="readonly-note">
        <AppIcon name="lock" :size="13" />
        当前角色为只读，仅系统管理员可修改参数
      </span>
    </div>

    <div v-if="error" class="empty">
      <AppIcon name="alert" :size="22" />
      {{ error }}
    </div>
    <div v-else-if="loading" class="settings-loading"><span class="spinner" /> 正在加载系统配置…</div>

    <template v-else-if="tab === 'params' && form">
      <div class="param-grid">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />排产窗口与时限</div>
            <span class="panel-sub">冻结窗口 · 班次 · 超时策略</span>
          </div>
          <div class="panel-body form-grid">
            <label class="field">
              <span class="field-label">冻结窗口（天）</span>
              <input v-model.number="form.freeze_days" type="number" min="0" max="14" class="input" :disabled="!canEdit" />
              <span class="field-hint">冻结期内已下发工序不参与重排</span>
            </label>
            <label class="field">
              <span class="field-label">审批超时（分钟）</span>
              <input v-model.number="form.approval_timeout_minutes" type="number" min="5" max="120" class="input" :disabled="!canEdit" />
              <span class="field-hint">超时自动升级至生产指挥部</span>
            </label>
            <label class="field">
              <span class="field-label">求解器超时（秒）</span>
              <input v-model.number="form.solver_timeout_seconds" type="number" min="3" max="600" class="input" :disabled="!canEdit" />
              <span class="field-hint">有限产能求解时间上限</span>
            </label>
            <label class="field">
              <span class="field-label">班次天数（天/周）</span>
              <input v-model.number="form.shift.days" type="number" min="1" max="7" class="input" :disabled="!canEdit" />
              <span class="field-hint">默认周日停机检修</span>
            </label>
            <label class="field">
              <span class="field-label">班次开始（时）</span>
              <input v-model.number="form.shift.start" type="number" min="0" max="23" class="input" :disabled="!canEdit" />
            </label>
            <label class="field">
              <span class="field-label">班次结束（时）</span>
              <input v-model.number="form.shift.end" type="number" min="1" max="24" class="input" :disabled="!canEdit" />
            </label>
            <div class="toggle-row">
              <div>
                <span class="field-label">审批超时自动升级</span>
                <span class="field-hint">15 分钟未审自动 escalate 并生成告警</span>
              </div>
              <button
                class="toggle"
                :class="{ on: form.auto_escalate }"
                type="button"
                :disabled="!canEdit"
                @click="form.auto_escalate = !form.auto_escalate"
              />
            </div>
            <div class="toggle-row">
              <div>
                <span class="field-label">写保护网关</span>
                <span class="field-hint">禁止 LLM / 求解器直写 APS / MES</span>
              </div>
              <button
                class="toggle"
                :class="{ on: form.write_shield }"
                type="button"
                :disabled="!canEdit"
                @click="form.write_shield = !form.write_shield"
              />
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />质量阈值</div>
            <span class="panel-sub">门禁与置信度</span>
          </div>
          <div class="panel-body threshold-body">
            <div v-for="(value, key) in form.thresholds" :key="key" class="threshold-row">
              <div class="threshold-head">
                <span>{{ THRESHOLD_LABELS[key] || key }}</span>
                <strong class="num">{{ key === 'confidence' ? value : `${value}%` }}</strong>
              </div>
              <input
                v-model.number="form.thresholds[key]"
                type="range"
                :min="key === 'confidence' ? 0.5 : 60"
                :max="key === 'confidence' ? 0.99 : 100"
                :step="key === 'confidence' ? 0.01 : 1"
                class="range"
                :disabled="!canEdit"
              />
            </div>
            <div class="threshold-note">
              <AppIcon name="info" :size="14" />
              <p>数据质量低于阈值将阻断 L0 门禁；齐套率目标用于 M-03 校验基线；置信度低于阈值方案需人工复核。</p>
            </div>
          </div>
        </section>
      </div>

      <section class="panel weights-panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />多目标权重</div>
          <span class="panel-sub" :class="{ 'text-warning': !weightBalanced }">
            权重合计 {{ (weightSum * 100).toFixed(0) }}%{{ weightBalanced ? ' · 已均衡' : ' · 建议合计 100%' }}
          </span>
        </div>
        <div class="panel-body">
          <div class="weight-grid">
            <div v-for="(value, key) in form.weights" :key="key" class="weight-item">
              <div class="weight-head">
                <span>{{ WEIGHT_LABELS[key] || key }}</span>
                <strong class="num" :style="{ color: weightTone(value) }">{{ Math.round(value * 100) }}%</strong>
              </div>
              <input
                v-model.number="form.weights[key]"
                type="range"
                min="0"
                max="1"
                step="0.05"
                class="range"
                :disabled="!canEdit"
              />
              <div class="weight-bar">
                <i :style="{ width: `${Math.min(100, value * 100)}%`, background: weightTone(value) }" />
              </div>
            </div>
          </div>

          <div class="scenario-grid">
            <div v-for="[code, scenario] in scenarioList" :key="code" class="scenario-card">
              <div class="scenario-head">
                <span class="scenario-code">{{ code }}</span>
                <span class="badge badge-muted">预设场景</span>
              </div>
              <h3>{{ scenario.objective }}</h3>
              <div class="scenario-weights">
                <span v-for="(value, key) in scenario.weights" :key="key">
                  {{ WEIGHT_LABELS[key] || key }} <strong class="num">{{ Math.round(value * 100) }}%</strong>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="canEdit" class="panel-foot save-foot">
          <span class="muted">修改将写入审计链并立即作用于下一次排产</span>
          <div class="flex gap-8">
            <button class="btn btn-ghost btn-sm" type="button" @click="reset">恢复生效值</button>
            <button class="btn btn-primary btn-sm" type="button" :disabled="saving" @click="save">
              <span v-if="saving" class="spinner" />
              保存参数
            </button>
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="tab === 'llm' && llmForm && llm">
      <div class="param-grid">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />内网模型接入</div>
            <span class="badge" :class="llmForm.enabled ? 'badge-accent' : 'badge-muted'">
              {{ llmForm.enabled ? '模型推理' : '确定性编排' }}
            </span>
          </div>
          <div class="panel-body form-grid">
            <div class="toggle-row">
              <div>
                <span class="field-label">启用内网模型编排</span>
                <span class="field-hint">关闭时 ReAct 阶段全部走确定性叙述，排产不依赖模型</span>
              </div>
              <button class="toggle" :class="{ on: llmForm.enabled }" type="button" :disabled="!canEdit" @click="llmForm.enabled = !llmForm.enabled" />
            </div>
            <label class="field span-2">
              <span class="field-label">OpenAI 兼容端点（base_url）</span>
              <input v-model="llmForm.base_url" class="input mono" placeholder="https://llm.intra.local/v1" :disabled="!canEdit" />
              <span class="field-hint">必须是 https（本机回环除外），且主机命中内网后缀，否则保存被拒绝</span>
            </label>
            <label class="field">
              <span class="field-label">模型名</span>
              <input v-model="llmForm.model" class="input mono" placeholder="qwen2.5-72b-instruct" :disabled="!canEdit" />
            </label>
            <label class="field">
              <span class="field-label">密钥环境变量名</span>
              <input v-model="llmForm.api_key_env" class="input mono" placeholder="LISA_LLM_API_KEY" :disabled="!canEdit" />
              <span class="field-hint flex" :class="llm.credential_present ? 'text-success' : 'text-warning'">
                <AppIcon :name="llm.credential_present ? 'check' : 'alert'" :size="12" />
                {{ llm.credential_present ? `${llm.credential_source} 已在服务端环境变量中就绪` : `${llm.credential_source || 'LISA_LLM_API_KEY'} 尚未设置，启用后会自动降级` }}
              </span>
            </label>
            <label class="field">
              <span class="field-label">单次请求超时（秒）</span>
              <input v-model.number="llmForm.timeout_seconds" type="number" min="1" max="120" class="input" :disabled="!canEdit" />
            </label>
            <label class="field">
              <span class="field-label">模型最多接管阶段数</span>
              <input v-model.number="llmForm.max_steps" type="number" min="1" max="24" class="input" :disabled="!canEdit" />
              <span class="field-hint">超出部分自动改用确定性叙述，避免整轮编排卡在模型上</span>
            </label>
            <label class="field">
              <span class="field-label">温度</span>
              <input v-model.number="llmForm.temperature" type="number" min="0" max="1" step="0.05" class="input" :disabled="!canEdit" />
            </label>
            <label class="field">
              <span class="field-label">单次观察文本上限（字）</span>
              <input v-model.number="llmForm.max_observation_chars" type="number" min="200" max="8000" class="input" :disabled="!canEdit" />
            </label>
            <div class="toggle-row">
              <div>
                <span class="field-label">仅允许内网主机</span>
                <span class="field-hint">关闭后仍强制 https，但不再校验主机后缀</span>
              </div>
              <button class="toggle" :class="{ on: llmForm.internal_only }" type="button" :disabled="!canEdit" @click="llmForm.internal_only = !llmForm.internal_only" />
            </div>
            <label class="field">
              <span class="field-label">内网主机后缀</span>
              <input v-model="llmSuffixText" class="input mono" placeholder=".intra, .internal, .lan" :disabled="!canEdit" />
            </label>
            <label class="field span-2">
              <span class="field-label">送模型前脱敏字段</span>
              <input v-model="llmRedactText" class="input mono" placeholder="customer, product_name, supplier" :disabled="!canEdit" />
              <span class="field-hint">这些字段的值以 «客户#1» 形式化名后送入模型，回填叙述时再还原，明文不出内网模型边界</span>
            </label>
            <div v-if="llmError" class="llm-error"><AppIcon name="alert" :size="14" /> {{ llmError }}</div>
            <div v-if="llmResult" class="llm-result">
              <div><span>模型</span><strong>{{ llmResult.model }}</strong></div>
              <div><span>延迟</span><strong class="num">{{ llmResult.latency_ms }}ms</strong></div>
              <div><span>端点</span><strong class="mono">{{ llmResult.endpoint }}</strong></div>
              <div class="span-2"><span>回执</span><strong>{{ llmResult.echo }}</strong></div>
              <div class="span-2"><span>凭据</span><strong>{{ llmResult.credentials }}</strong></div>
            </div>
          </div>
          <div v-if="canEdit" class="panel-foot save-foot">
            <span class="muted">配置写入设置表并留审计，密钥只读环境变量、永不落库</span>
            <div class="flex gap-8">
              <button class="btn btn-sm" type="button" :disabled="llmTesting" @click="testLlm">
                <span v-if="llmTesting" class="spinner" />
                <AppIcon v-else name="play" :size="13" />
                {{ llmTesting ? '连接中…' : '测试连接' }}
              </button>
              <button class="btn btn-primary btn-sm" type="button" :disabled="llmSaving" @click="saveLlm">
                <span v-if="llmSaving" class="spinner" />
                保存配置
              </button>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />只读工具面（MCP）</div>
            <span class="panel-sub">{{ llm.mcp.tools.length }} 个工具 · {{ llm.mcp.protocol_version }}</span>
          </div>
          <div class="panel-body mcp-body">
            <div class="mcp-endpoint mono">
              <AppIcon name="terminal" :size="13" />
              POST {{ llm.mcp.endpoint }}
              <em>Bearer = 登录 token</em>
            </div>
            <p class="mcp-instructions">{{ llm.mcp.instructions }}</p>
            <div class="mcp-tools">
              <div v-for="entry in llm.mcp.tools" :key="entry.name" class="mcp-tool">
                <code>{{ entry.name }}</code>
                <p>{{ entry.description }}</p>
              </div>
            </div>
            <div class="mcp-runs">
              <div><span>近 20 次模型接管</span><strong class="num">{{ llm.runs.llm }}</strong></div>
              <div><span>近 20 次确定性降级</span><strong class="num">{{ llm.runs.fallback }}</strong></div>
            </div>
            <div v-if="llm.runs.last" class="mcp-last">
              最近一次：{{ llm.runs.last.mode === 'llm' ? `${llm.runs.last.model} 推理 ${llm.runs.last.calls} 轮` : llm.runs.last.reason }}
            </div>
          </div>
          <div class="panel-foot">
            写操作不在这张工具面上；模型只能选只读工具取数，所有数字由 LISA 代码实算后回填，越权调用被拒绝并记审计。
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="tab === 'security' && security">
      <div class="security-grid">
        <section class="panel shield-panel">
          <div class="panel-head">
            <div class="panel-title">
              <span class="title-mark" />
              写保护网关
              <StatusBadge :label="security.write_shield.enabled ? '启用' : '停用'" :tone="security.write_shield.enabled ? 'success' : 'danger'" />
            </div>
            <span class="panel-sub">{{ security.write_shield.status }}</span>
          </div>
          <div class="panel-body">
            <p class="security-desc">{{ security.write_shield.policy }}</p>
            <div class="shield-metrics">
              <div>
                <span>已拦截写入</span>
                <strong class="num text-danger">{{ formatNumber(security.write_shield.blocked_writes) }}</strong>
              </div>
              <div>
                <span>拦截目标</span>
                <strong>100%</strong>
              </div>
              <div>
                <span>审计落链</span>
                <strong class="text-success">实时</strong>
              </div>
            </div>
            <button class="btn btn-teal" type="button" :disabled="shieldTesting" @click="testShield">
              <span v-if="shieldTesting" class="spinner" />
              <AppIcon v-else name="shield" :size="15" />
              {{ shieldTesting ? '演练中…' : '执行写保护演练' }}
            </button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />安全基线</div>
            <span class="panel-sub">加密 · 审计 · 签名</span>
          </div>
          <div class="panel-body security-facts">
            <div class="fact">
              <span class="fact-label">传输加密</span>
              <strong>{{ security.encryption.transport }}</strong>
            </div>
            <div class="fact">
              <span class="fact-label">脱敏策略</span>
              <strong>{{ security.encryption.desensitization }}</strong>
            </div>
            <div class="fact">
              <span class="fact-label">数据边界</span>
              <strong>{{ security.encryption.data_boundary }}</strong>
            </div>
            <div class="fact">
              <span class="fact-label">审计哈希链</span>
              <strong>{{ security.audit.hash_chain }} · {{ security.audit.worm ? 'WORM 只追加' : '普通存储' }}</strong>
            </div>
            <div class="fact">
              <span class="fact-label">审计留存</span>
              <strong>{{ security.audit.retention }}</strong>
            </div>
            <div class="fact">
              <span class="fact-label">电子签名</span>
              <strong>{{ security.electronic_signature.algorithm }}</strong>
            </div>
            <div class="fact full">
              <span class="fact-label">审批级别</span>
              <div class="fact-chips">
                <span v-for="level in security.electronic_signature.levels" :key="level" class="chip">{{ level }}</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section v-if="security.clearance && clearanceForm" class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <span class="title-mark" />
            密级模型（ABAC 数据维度）
            <StatusBadge
              :label="clearanceForm.enabled ? '查询级过滤启用' : '过滤已关闭'"
              :tone="clearanceForm.enabled ? 'success' : 'danger'"
            />
          </div>
          <span class="panel-sub">
            你的密级 {{ security.clearance.your_level || '未标注' }} · 可读 {{ security.clearance.visible_levels }} /
            {{ security.clearance.total_levels }} 级
          </span>
        </div>
        <div class="panel-body clearance-body">
          <p class="security-desc">
            等级表按「低 → 高」有序排列，第 1 级看得最少、最后一级看得最多。人的密级来自账号（用户与角色页），
            数据的密级来自工单。等级表配错不会退化成「全都能看」：读取会直接报错，改错了会被立刻发现。
          </p>

          <div class="level-list">
            <div v-for="(level, index) in clearanceForm.levels" :key="index" class="level-row">
              <span class="level-rank num">{{ index + 1 }}</span>
              <input
                v-model="clearanceForm.levels[index]"
                class="input level-input"
                :disabled="!canEdit"
                placeholder="等级名"
              />
              <span class="level-count">
                工单 {{ security.clearance.orders_by_level[level] ?? 0 }} 张 ·
                账号 {{ security.clearance.users_by_level[level] ?? 0 }} 个
              </span>
              <div class="level-ops">
                <button class="btn btn-ghost btn-sm" type="button" :disabled="!canEdit || index === 0" @click="moveLevel(index, -1)">
                  <AppIcon name="chevronRight" :size="12" class="rotate-up" />
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :disabled="!canEdit || index === clearanceForm.levels.length - 1"
                  @click="moveLevel(index, 1)"
                >
                  <AppIcon name="chevronRight" :size="12" class="rotate-down" />
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :disabled="!canEdit || clearanceForm.levels.length <= 2"
                  @click="removeLevel(index)"
                >
                  <AppIcon name="close" :size="12" />
                </button>
              </div>
            </div>
          </div>

          <div class="level-add">
            <input v-model="newLevel" class="input" placeholder="新增等级名，如「绝密」" @keyup.enter="addLevel" />
            <button class="btn btn-ghost" type="button" :disabled="!canEdit || !newLevel.trim()" @click="addLevel">
              <AppIcon name="plus" :size="13" />
              追加为最高级
            </button>
          </div>

          <div class="clearance-fields">
            <label class="field">
              <span class="field-label">未标注数据的默认密级</span>
              <span class="field-hint">工单没打标时按这一级处理，标得越高越保守</span>
              <select v-model="clearanceForm.data_default" class="select" :disabled="!canEdit">
                <option v-for="level in clearanceForm.levels" :key="level" :value="level">{{ level }}</option>
              </select>
            </label>
            <div class="toggle-row">
              <div>
                <span class="field-label">如实上报被隐藏的条数</span>
                <span class="field-hint">界面上显示「N 条因密级未显示」，而不是静默少掉</span>
              </div>
              <button
                class="toggle"
                :class="{ on: clearanceForm.report_hidden }"
                type="button"
                :disabled="!canEdit"
                @click="clearanceForm.report_hidden = !clearanceForm.report_hidden"
              />
            </div>
            <div class="toggle-row">
              <div>
                <span class="field-label">密级过滤总开关</span>
                <span class="field-hint">关闭后所有账号看到全量数据，仅用于密级建模尚未验收的调试期</span>
              </div>
              <button
                class="toggle"
                :class="{ on: clearanceForm.enabled }"
                type="button"
                :disabled="!canEdit"
                @click="clearanceForm.enabled = !clearanceForm.enabled"
              />
            </div>
          </div>

          <div v-if="orphanCount > 0" class="clearance-note">
            <AppIcon name="lock" :size="14" />
            <span>
              有 <strong class="num">{{ orphanCount }}</strong> 张工单的密级标签不在当前等级表里
              （{{ Object.entries(clearanceOrphans).map(([level, count]) => `${level} ${count}`).join('、') }}）：
              按 fail-closed 它们对任何人都不显示。要么把等级加回表里，要么重新打标，不要靠关闭总开关绕过。
            </span>
          </div>

          <div v-if="!clearanceForm.enabled" class="clearance-note">
            <AppIcon name="warning" :size="14" />
            <span>过滤已关闭：此刻不脱密、不分级，任何能登录的账号都能读到机密工单。投产验收前必须重新启用。</span>
          </div>

          <div v-for="issue in clearanceErrors" :key="issue" class="clearance-error">{{ issue }}</div>
        </div>
        <div class="panel-foot clearance-foot">
          <span class="fs-12 muted">生效范围：订单 / 齐套 / 甘特与方案条目 / 扰动事件 / 全局搜索 / 统计 / CSV 导出 / 驾驶舱 / MCP 工具面</span>
          <button
            class="btn btn-primary"
            type="button"
            :disabled="!canEdit || clearanceSaving || clearanceErrors.length > 0"
            @click="saveClearance"
          >
            <span v-if="clearanceSaving" class="spinner" />
            <AppIcon v-else name="shield" :size="14" />
            保存密级策略
          </button>
        </div>
      </section>

      <section v-if="security.plants && plantForm" class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <span class="title-mark" />
            厂区范围（读取隔离，非多租户）
            <StatusBadge
              :label="plantForm.enabled ? '按厂区过滤启用' : '全厂数据可见'"
              :tone="plantForm.enabled ? 'success' : 'muted'"
            />
          </div>
          <span class="panel-sub">
            你的范围 {{ security.plants.your_scope ? security.plants.your_scope.join('、') : '全部厂区' }} ·
            可见资源 {{ security.plants.resource_count }} 台
          </span>
        </div>
        <div class="panel-body clearance-body">
          <p class="security-desc">
            客户是单一法人、两厂区 / 10 个分厂，所以这里做的是「同一个库里的读取范围隔离」，不是 SaaS 多租户：
            数据不分区存放，只在查询时按账号勾选的厂区收窄。没勾厂区的账号代表不受限制，而不是什么都看不见。
          </p>

          <div class="level-list">
            <div v-for="(name, index) in plantForm.names" :key="index" class="level-row">
              <span class="level-rank num">{{ index + 1 }}</span>
              <input v-model="plantForm.names[index]" class="input level-input" :disabled="!canEdit" placeholder="厂区名" />
              <span class="level-count">
                工单 {{ security.plants.orders_by_plant[name] ?? 0 }} 张
              </span>
              <div class="level-ops">
                <button class="btn btn-ghost btn-sm" type="button" :disabled="!canEdit" @click="removePlant(index)">
                  <AppIcon name="close" :size="12" />
                </button>
              </div>
            </div>
          </div>

          <div class="level-add">
            <input v-model="newPlant" class="input" placeholder="新增厂区名，如「三厂 / 外协基地」" @keyup.enter="addPlant" />
            <button class="btn btn-ghost" type="button" :disabled="!canEdit || !newPlant.trim()" @click="addPlant">
              <AppIcon name="plus" :size="13" />
              追加厂区
            </button>
          </div>

          <div class="clearance-fields">
            <label class="field">
              <span class="field-label">未标注厂区的数据默认归入</span>
              <span class="field-hint">主数据没给厂区时按这个厂区算，落在清单外的谁都看不到</span>
              <select v-model="plantForm.data_default" class="select" :disabled="!canEdit">
                <option v-for="name in plantForm.names" :key="name" :value="name">{{ name }}</option>
              </select>
            </label>
            <div class="toggle-row">
              <div>
                <span class="field-label">厂区过滤总开关</span>
                <span class="field-hint">投产前厂区归属没确认清楚前保持关闭：开了会立刻有人看不见数据</span>
              </div>
              <button
                class="toggle"
                :class="{ on: plantForm.enabled }"
                type="button"
                :disabled="!canEdit"
                @click="plantForm.enabled = !plantForm.enabled"
              />
            </div>
          </div>

          <div class="scope-table">
            <div class="scope-head">
              <span>账号</span>
              <span>角色</span>
              <span>厂区范围（不勾 = 全厂）</span>
              <span />
            </div>
            <div v-for="person in plantPeople" :key="person.username" class="scope-row">
              <div>
                <strong>{{ person.name }}</strong>
                <span class="mono fs-11">{{ person.username }}</span>
              </div>
              <span class="fs-12 muted">{{ shortRole(person.role) }}</span>
              <div class="scope-chips">
                <button
                  v-for="name in plantForm.names"
                  :key="name"
                  class="chip"
                  :class="{ active: (scopeDraft[person.username] || []).includes(name) }"
                  :disabled="!canEdit"
                  type="button"
                  @click="togglePlantScope(person.username, name)"
                >
                  {{ name }}
                </button>
              </div>
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="!canEdit || (scopeDraft[person.username] || []).join('、') === person.plants.join('、')"
                @click="saveScope(person.username)"
              >
                保存
              </button>
            </div>
          </div>

          <div v-if="unknownClaimed.length" class="clearance-note">
            <AppIcon name="warning" :size="14" />
            <span>
              有账号勾选了清单里不存在的厂区（{{ unknownClaimed.join('、') }}）：按 fail-closed 这些账号一条数据都看不到。
              要么把厂区加进清单，要么改回真实厂区。
            </span>
          </div>

          <div v-if="orphanPlantCount > 0" class="clearance-note">
            <AppIcon name="lock" :size="14" />
            <span>
              有 <strong class="num">{{ orphanPlantCount }}</strong> 张工单的厂区不在清单里
              （{{ Object.entries(orphanPlants).map(([name, count]) => `${name} ${count}`).join('、') }}）：
              只有不受厂区限制的账号能看到，请修正主数据。
            </span>
          </div>

          <div v-for="issue in plantErrors" :key="issue" class="clearance-error">{{ issue }}</div>
        </div>
        <div class="panel-foot clearance-foot">
          <span class="fs-12 muted">生效范围：订单 / 齐套 / 甘特与方案条目 / 全局搜索 / 统计 / CSV 导出 / 驾驶舱 / MCP 工具面，与密级两条叠加</span>
          <button
            class="btn btn-primary"
            type="button"
            :disabled="!canEdit || plantSaving || plantErrors.length > 0"
            @click="savePlants"
          >
            <span v-if="plantSaving" class="spinner" />
            <AppIcon v-else name="layers" :size="14" />
            保存厂区范围
          </button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">
            <span class="title-mark" />
            ABAC 权限矩阵
            <span class="badge badge-danger">越权拒绝 {{ security.abac.denied_events }} 次</span>
          </div>
          <span class="panel-sub">{{ security.abac.policy_engine }}</span>
        </div>
        <div class="matrix-body">
          <div v-for="role in security.abac.matrix" :key="role.role" class="matrix-row">
            <div class="matrix-role">
              <strong>{{ role.label }}</strong>
              <span class="mono">{{ role.role }}</span>
            </div>
            <div class="matrix-perms">
              <span v-for="(label, index) in role.permission_labels || role.permissions" :key="index" class="perm-chip">
                {{ label }}
              </span>
            </div>
          </div>
        </div>
        <div class="panel-foot">权限策略随会话实时校验，所有越权请求被拒绝并写入审计哈希链</div>
      </section>
    </template>

    <template v-else-if="tab === 'users'">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />用户与角色</div>
          <span class="panel-sub">{{ users.length }} 个内网账号</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>账号</th>
                <th>角色</th>
                <th>密级</th>
                <th>部门</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td>
                  <div class="user-cell">
                    <span class="avatar" :style="{ background: user.avatar_color }">{{ user.name.slice(0, 1) }}</span>
                    <span class="cell-strong">{{ user.name }}</span>
                  </div>
                </td>
                <td class="mono">{{ user.username }}</td>
                <td>
                  <span class="badge" :class="user.role === 'admin' ? 'badge-accent' : 'badge-muted'">
                    {{ user.role_label || shortRole(user.role) }}
                  </span>
                </td>
                <td>{{ user.clearance }}</td>
                <td>{{ user.department }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="panel-foot">账号体系对接内网统一身份认证，角色权限由 ABAC 策略中心统一下发</div>
      </section>
    </template>

    <template v-else-if="tab === 'system'">
      <div class="system-grid">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />运行信息</div>
            <StatusBadge label="在线" tone="success" />
          </div>
          <div class="panel-body">
            <div class="kv"><span class="k">系统名称</span><span class="v">{{ meta?.name }}</span></div>
            <div class="kv"><span class="k">英文名称</span><span class="v">{{ meta?.name_en }}</span></div>
            <div class="kv"><span class="k">版本</span><span class="v mono">{{ meta?.version }}</span></div>
            <div class="kv"><span class="k">部署环境</span><span class="v">{{ meta?.environment }}</span></div>
            <div class="kv"><span class="k">数据库引擎</span><span class="v mono">{{ dbEngineLabel }}</span></div>
            <div class="kv"><span class="k">约束规模</span><span class="v">{{ meta?.constraints?.hard || 'HC-01~14' }} · {{ meta?.constraints?.soft || 'SC-01~13' }}</span></div>
            <div class="kv">
              <span class="k">角色</span>
              <span class="v">{{ meta?.roles.map((role) => role.label).join(' / ') }}</span>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title"><span class="title-mark" />数据导出</div>
            <span class="panel-sub">CSV · 内网下载</span>
          </div>
          <div class="panel-body export-body">
            <div class="export-row">
              <div>
                <strong>订单台账导出</strong>
                <span>订单号、产品、交期、状态与齐套状态</span>
              </div>
              <button
                v-if="auth.can('export:read')"
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="exporting === 'orders'"
                @click="exportFile('orders')"
              >
                <span v-if="exporting === 'orders'" class="spinner" />
                <AppIcon v-else name="download" :size="13" />
                导出
              </button>
              <span v-else class="muted fs-12">无导出权限</span>
            </div>
            <div class="export-row">
              <div>
                <strong>审计日志导出</strong>
                <span>含哈希链、操作人、结果与密级字段</span>
              </div>
              <button
                v-if="auth.can('audit:read')"
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="exporting === 'audit'"
                @click="exportFile('audit')"
              >
                <span v-if="exporting === 'audit'" class="spinner" />
                <AppIcon v-else name="download" :size="13" />
                导出
              </button>
              <span v-else class="muted fs-12">无导出权限</span>
            </div>
            <div class="export-note">
              <AppIcon name="shield" :size="14" />
              导出行为同样写入审计哈希链，禁止将数据带出内网。
            </div>
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />数据规模</div>
          <span class="panel-sub">{{ dbEngineLabel }} · 实时统计</span>
        </div>
        <div class="panel-body stat-grid">
          <div v-for="tile in statTiles" :key="tile.label" class="stat-tile">
            <span>{{ tile.label }}</span>
            <strong class="num">{{ tile.value === undefined ? '—' : formatNumber(tile.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-if="backups" class="panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />备份与恢复</div>
          <span class="panel-sub">{{ dbEngineLabel }} · 保留最近 {{ backups.keep }} 份</span>
        </div>
        <div class="panel-body">
          <div class="backup-actions">
            <button class="btn btn-primary btn-sm" type="button" :disabled="backupBusy" @click="runBackup">
              <span v-if="backupBusy" class="spinner" />
              <AppIcon v-else name="download" :size="13" />
              立即快照
            </button>
            <span class="muted fs-12 mono">{{ backups.backup_dir }}</span>
          </div>
          <p v-if="!backups.items.length" class="muted fs-12">
            还没有快照：整库回滚的前提是先有可校验的快照，点「立即快照」或在服务器上执行
            <code class="mono">python -m app.management backup</code>。
          </p>
          <table v-else class="scope-table">
            <thead class="scope-head">
              <tr>
                <th>快照</th>
                <th>生成时间</th>
                <th>行数</th>
                <th>大小</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in backups.items.slice(0, 6)" :key="item.file" class="scope-row">
                <td class="mono">{{ item.file.replace('lisa-backup-', '') }}</td>
                <td class="mono">{{ (item.created_at || '—').replace('T', ' ').slice(0, 19) }}</td>
                <td>{{ item.unreadable ? '文件不可读' : formatNumber(item.total_rows || 0) }}</td>
                <td>{{ formatNumber(Math.round((item.bytes || 0) / 1024)) }} KB</td>
                <td>
                  <button
                    v-if="!item.unreadable && item.has_checksum"
                    class="btn btn-ghost btn-sm"
                    type="button"
                    :disabled="!!verifying"
                    @click="checkBackup(item.file)"
                  >
                    <span v-if="verifying === item.file" class="spinner" />
                    <span v-else>校验</span>
                  </button>
                  <span v-else class="muted fs-12">缺 .sha256</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div class="backup-native">
            <span class="muted fs-12">{{ backups.native.note }}</span>
            <code class="mono">{{ backups.native.dump }}</code>
            <code class="mono">{{ backups.native.restore }}</code>
            <div class="restore-hint">
              <AppIcon name="shield" :size="14" />
              {{ backups.restore }}
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}

.tabs-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.tab-count {
  margin-left: 5px;
  font-size: 10px;
  opacity: 0.7;
}

.readonly-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}

.settings-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.param-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.field-hint {
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.5;
}

.toggle-row {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.toggle-row > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 模型编排 */
.form-grid .span-2 {
  grid-column: span 2;
}
.field-hint.flex {
  display: flex;
  align-items: center;
  gap: 5px;
}
.llm-error {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--danger-soft);
  background: var(--danger-soft);
  font-size: 11px;
  line-height: 1.55;
  color: var(--danger);
}
.llm-result {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.llm-result .span-2 {
  grid-column: 1 / -1;
}
.llm-result div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.llm-result span {
  font-size: 10px;
  color: var(--text-3);
}
.llm-result strong {
  font-size: 11.5px;
  color: var(--text-1);
  font-weight: 600;
  word-break: break-all;
}
.mcp-body {
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.mcp-endpoint {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  font-size: 11px;
  color: var(--text-1);
}
.mcp-endpoint em {
  font-style: normal;
  margin-left: auto;
  font-size: 10px;
  color: var(--text-3);
}
.mcp-instructions {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-3);
}
.mcp-tools {
  display: flex;
  flex-direction: column;
  gap: 9px;
  max-height: 330px;
  overflow: auto;
  padding-right: 4px;
}
.mcp-tool code {
  font-size: 10.5px;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 1px 6px;
  border-radius: 4px;
}
.mcp-tool p {
  margin: 3px 0 0;
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--text-3);
}
.mcp-runs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.mcp-runs div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.mcp-runs span {
  font-size: 10px;
  color: var(--text-3);
}
.mcp-runs strong {
  font-size: 15px;
  color: var(--text-1);
}
.mcp-last {
  font-size: 10.5px;
  color: var(--text-2);
  line-height: 1.55;
}

.threshold-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}.threshold-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 6px;
}

.threshold-head strong {
  color: var(--accent);
  font-size: 13px;
}

.range {
  width: 100%;
  accent-color: var(--accent);
  height: 4px;
  cursor: pointer;
}

.range:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.threshold-note {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  border: 1px dashed var(--accent-line);
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.65;
}

.threshold-note svg {
  flex: none;
  color: var(--accent);
  margin-top: 2px;
}

.weight-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.weight-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 7px;
}

.weight-head strong {
  font-family: var(--font-display);
  font-size: 17px;
}

.weight-bar {
  height: 4px;
  border-radius: 3px;
  background: var(--panel-inset);
  overflow: hidden;
  margin-top: 7px;
}

.weight-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  border-top: 1px solid var(--border);
  padding-top: 14px;
}

.scenario-card {
  padding: 13px 15px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.scenario-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}

.scenario-code {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
}

.scenario-card h3 {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}

.scenario-weights {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10.5px;
  color: var(--text-3);
}

.scenario-weights strong {
  color: var(--text-2);
}

.save-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.security-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.security-desc {
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-2);
  padding: 12px 14px;
  border-left: 2px solid var(--teal);
  background: var(--panel-inset);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  margin-bottom: 14px;
}

.shield-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.shield-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.shield-metrics span {
  font-size: 10.5px;
  color: var(--text-3);
}

.shield-metrics strong {
  font-size: 16px;
  color: var(--text);
}

.security-facts {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.fact {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.fact:last-child {
  border-bottom: 0;
}

.fact.full {
  flex-direction: column;
  gap: 6px;
}

.fact-label {
  color: var(--text-3);
  flex: none;
}

.fact strong {
  color: var(--text);
  font-weight: 550;
  text-align: right;
}

.fact-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.perm-chip {
  font-size: 10.5px;
  padding: 2px 8px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  color: var(--text-2);
  white-space: nowrap;
}

.matrix-body {
  display: flex;
  flex-direction: column;
}

.matrix-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 16px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
}

.matrix-row:last-child {
  border-bottom: 0;
}

.matrix-role {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.matrix-role strong {
  font-size: 12.5px;
  color: var(--text);
}

.matrix-role span {
  font-size: 10px;
  color: var(--text-3);
}

.matrix-perms {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 9px;
}

.avatar {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  border-radius: 8px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 700;
  flex: none;
}

.system-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 16px;
  margin-bottom: 16px;
}

.export-body {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.export-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 11px 0;
  border-bottom: 1px solid var(--border);
}

.export-row > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.export-row strong {
  font-size: 12.5px;
  color: var(--text);
}

.export-row span {
  font-size: 11px;
  color: var(--text-3);
}

.export-note {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  margin-top: 12px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  border: 1px dashed var(--border-strong);
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
}

.export-note svg {
  flex: none;
  color: var(--accent);
  margin-top: 2px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 8px;
}

.stat-tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 11px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.stat-tile span {
  font-size: 10px;
  color: var(--text-3);
}

.stat-tile strong {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--text);
}

.clearance-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.level-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.level-row {
  display: grid;
  grid-template-columns: 26px minmax(120px, 220px) minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.level-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  font-size: 11px;
  color: var(--text-2);
}

.level-input {
  height: 30px;
  font-size: 12.5px;
}

.level-count {
  font-size: 11.5px;
  color: var(--text-3);
}

.level-ops {
  display: flex;
  gap: 4px;
}

.rotate-up {
  transform: rotate(-90deg);
}

.rotate-down {
  transform: rotate(90deg);
}

.level-add {
  display: flex;
  gap: 8px;
  max-width: 420px;
}

.level-add .input {
  flex: 1;
}

.clearance-fields {
  display: grid;
  grid-template-columns: minmax(0, 260px) repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}

.clearance-error {
  font-size: 12px;
  color: var(--danger);
}

/* 厂区范围：按人头勾选 */
.scope-table { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.scope-head, .scope-row {
  display: grid;
  grid-template-columns: 150px 88px 1fr 64px;
  align-items: center;
  gap: 10px;
}
.scope-head { font-size: 10px; color: var(--text-3); padding: 0 11px; }
.scope-row {
  padding: 8px 11px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
}
.scope-row strong { display: block; font-size: 12px; }
.scope-chips { display: flex; gap: 6px; flex-wrap: wrap; }

.backup-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.backup-native {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}

.backup-native code {
  font-size: 11px;
  color: var(--text-2);
  word-break: break-all;
}

.restore-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}

.clearance-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 1279px) {
  .weight-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .stat-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 1023px) {
  .param-grid,
  .security-grid,
  .system-grid {
    grid-template-columns: 1fr;
  }
  .form-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .scenario-grid {
    grid-template-columns: 1fr;
  }
  .clearance-fields {
    grid-template-columns: 1fr;
  }
  .level-row {
    grid-template-columns: 26px minmax(0, 1fr) auto;
  }
  .level-row .level-count {
    grid-column: 2 / -1;
  }
}

@media (max-width: 767px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .weight-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .shield-metrics {
    grid-template-columns: 1fr;
  }
  .matrix-row {
    grid-template-columns: 1fr;
    gap: 7px;
    padding: 12px 14px;
  }
  .export-row {
    flex-wrap: wrap;
  }
  .save-foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
