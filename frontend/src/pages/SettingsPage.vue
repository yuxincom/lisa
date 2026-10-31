<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { systemApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type {
  MetaInfo,
  ScenarioMeta,
  SecurityInfo,
  SettingsValues,
  User,
} from '@/types'
import { formatNumber, shortRole } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'

type Tab = 'params' | 'security' | 'users' | 'system'
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

const tabs = computed(() => [
  { key: 'params' as Tab, label: '排产参数' },
  { key: 'security' as Tab, label: '安全合规' },
  { key: 'users' as Tab, label: '用户与角色', count: users.value.length },
  { key: 'system' as Tab, label: '系统信息' },
])

function weightTone(value: number) {
  return value >= 0.35 ? 'var(--accent)' : value >= 0.2 ? 'var(--teal)' : 'var(--blue)'
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
    users.value = usersRes.items || []
    meta.value = metaRes
    stats.value = statsRes
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
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

async function testShield() {
  shieldTesting.value = true
  try {
    const res = await systemApi.writeShieldTest()
    security.value = await systemApi.security()
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
            <div class="kv"><span class="k">数据库引擎</span><span class="v mono">{{ stats?.db_engine || '—' }}</span></div>
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
          <span class="panel-sub">本地 SQLite · 可切换 PostgreSQL</span>
        </div>
        <div class="panel-body stat-grid">
          <div v-for="tile in statTiles" :key="tile.label" class="stat-tile">
            <span>{{ tile.label }}</span>
            <strong class="num">{{ tile.value === undefined ? '—' : formatNumber(tile.value) }}</strong>
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

.threshold-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.threshold-head {
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
