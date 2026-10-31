<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { alertsApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { Alert } from '@/types'
import {
  ALERT_TYPE_LABEL,
  SEVERITY_LABEL,
  alertTone,
  formatDateTime,
  relativeTime,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'

interface AlertSummary {
  total: number
  open: number
  acked: number
  levels: { level: string; count: number }[]
  open_levels: { level: string; count: number }[]
  fatal_open?: number
}

const LEVELS = [
  { key: 'fatal', label: '致命' },
  { key: 'critical', label: '严重' },
  { key: 'warning', label: '警告' },
  { key: 'info', label: '提示' },
]

const auth = useAuthStore()
const ui = useUiStore()

const summary = ref<AlertSummary | null>(null)
const alerts = ref<Alert[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('open')
const levelFilter = ref('')
const search = ref('')
const selected = ref<Set<number>>(new Set())
const ackingId = ref<number | null>(null)
const ackingBatch = ref(false)
let searchTimer: number | undefined

const canAck = computed(() => auth.can('alerts:ack'))
const openAlerts = computed(() => alerts.value.filter((alert) => alert.status === 'open'))
const allSelected = computed(
  () => openAlerts.value.length > 0 && openAlerts.value.every((alert) => selected.value.has(alert.id)),
)

const levelCount = (key: string) =>
  summary.value?.open_levels.find((item) => item.level === key)?.count ??
  summary.value?.levels.find((item) => item.level === key)?.count ??
  0

const statusTabs = computed(() => [
  { key: '', label: '全部', count: summary.value?.total ?? 0 },
  { key: 'open', label: '待确认', count: summary.value?.open ?? 0 },
  { key: 'acked', label: '已确认', count: summary.value?.acked ?? 0 },
])

async function loadSummary() {
  try {
    summary.value = await alertsApi.summary()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadAlerts() {
  loading.value = true
  error.value = ''
  try {
    const res = await alertsApi.list({
      status: statusFilter.value || undefined,
      level: levelFilter.value || undefined,
      search: search.value.trim() || undefined,
      limit: 200,
    })
    alerts.value = res.items
    selected.value = new Set()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function setStatus(key: string) {
  statusFilter.value = key
  loadAlerts()
}

function setLevel(key: string) {
  levelFilter.value = levelFilter.value === key ? '' : key
  loadAlerts()
}

function onSearch() {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(loadAlerts, 280)
}

function toggleSelect(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(openAlerts.value.map((alert) => alert.id))
}

async function ackOne(alert: Alert) {
  ackingId.value = alert.id
  try {
    await alertsApi.ackOne(alert.id)
    ui.success('告警已确认', alert.title)
    await Promise.all([loadSummary(), loadAlerts()])
  } catch (err) {
    ui.error('确认失败', errorMessage(err))
  } finally {
    ackingId.value = null
  }
}

async function ackBatch() {
  if (!selected.value.size) return
  ackingBatch.value = true
  try {
    const res = await alertsApi.ack([...selected.value])
    ui.success('批量确认完成', `已确认 ${res.acked} 条告警`)
    await Promise.all([loadSummary(), loadAlerts()])
  } catch (err) {
    ui.error('批量确认失败', errorMessage(err))
  } finally {
    ackingBatch.value = false
  }
}

function levelTone(level: string) {
  return alertTone(level)
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadAlerts()])
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L6 · 告警中心"
      title="异常与告警"
      subtitle="设备、齐套、审批、数据、变更全链路告警收敛，确认动作写入审计哈希链"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="loadAlerts">
          <AppIcon name="refresh" :size="15" />
          刷新
        </button>
        <button
          v-if="canAck"
          class="btn btn-primary"
          type="button"
          :disabled="!selected.size || ackingBatch"
          @click="ackBatch"
        >
          <span v-if="ackingBatch" class="spinner" />
          <AppIcon v-else name="check" :size="15" />
          批量确认{{ selected.size ? ` · ${selected.size}` : '' }}
        </button>
      </template>
      <template #meta>
        <span>待确认 <strong class="text-warning">{{ summary?.open ?? '—' }}</strong></span>
        <span class="meta-dot" />
        <span>致命 <strong class="text-danger">{{ summary?.fatal_open ?? levelCount('fatal') }}</strong></span>
      </template>
    </PageHeader>

    <div class="level-grid">
      <button
        v-for="level in LEVELS"
        :key="level.key"
        type="button"
        class="level-card panel"
        :class="[`tone-${level.key}`, { active: levelFilter === level.key }]"
        @click="setLevel(level.key)"
      >
        <div class="level-top">
          <span class="level-dot" />
          <span class="level-name">{{ level.label }}</span>
          <span class="level-total muted">{{ summary?.levels.find((l) => l.level === level.key)?.count ?? 0 }} 累计</span>
        </div>
        <strong class="level-count num">{{ levelCount(level.key) }}</strong>
        <span class="level-note">待立即确认</span>
      </button>
    </div>

    <section class="panel">
      <div class="panel-head alert-head">
        <div class="segmented">
          <button
            v-for="item in statusTabs"
            :key="item.key"
            type="button"
            :class="{ active: statusFilter === item.key }"
            @click="setStatus(item.key)"
          >
            {{ item.label }} <span class="seg-count">{{ item.count }}</span>
          </button>
        </div>
        <div class="toolbar">
          <div class="search-box">
            <AppIcon name="search" :size="14" />
            <input v-model="search" class="input" placeholder="标题 / 内容 / 编号" @input="onSearch" />
          </div>
          <button
            v-if="canAck && statusFilter !== 'acked' && openAlerts.length"
            class="btn btn-ghost btn-sm"
            type="button"
            @click="toggleAll"
          >
            <AppIcon name="check" :size="13" />
            {{ allSelected ? '取消全选' : '全选待确认' }}
          </button>
        </div>
      </div>

      <div v-if="error" class="empty">
        <AppIcon name="alert" :size="22" />
        {{ error }}
      </div>
      <div v-else-if="loading" class="alert-loading"><span class="spinner" /> 正在读取告警…</div>
      <div v-else-if="alerts.length" class="alert-list">
        <article
          v-for="alert in alerts"
          :key="alert.id"
          class="alert-row"
          :class="[`tone-${alert.level}`, { selected: selected.has(alert.id), acked: alert.status === 'acked' }]"
        >
          <button
            v-if="canAck && alert.status === 'open'"
            type="button"
            class="check-box"
            :class="{ on: selected.has(alert.id) }"
            :aria-label="selected.has(alert.id) ? '取消选择' : '选择告警'"
            @click="toggleSelect(alert.id)"
          >
            <AppIcon v-if="selected.has(alert.id)" name="check" :size="11" />
          </button>
          <span v-else class="check-placeholder" />

          <div class="alert-body">
            <div class="alert-headline">
              <StatusBadge :label="SEVERITY_LABEL[alert.level] || alert.level" :tone="levelTone(alert.level)" />
              <span class="badge badge-muted">{{ ALERT_TYPE_LABEL[alert.type] || alert.type }}</span>
              <span class="alert-code mono">{{ alert.code }}</span>
              <StatusBadge
                :label="alert.status === 'open' ? '待确认' : '已确认'"
                :tone="alert.status === 'open' ? 'warning' : 'success'"
                :dot="false"
              />
            </div>
            <h3>{{ alert.title }}</h3>
            <p>{{ alert.message }}</p>
            <div class="alert-meta">
              <span><AppIcon name="factory" :size="12" />{{ alert.source }}</span>
              <span><AppIcon name="target" :size="12" />{{ alert.related_type }}:{{ alert.related_id }}</span>
              <span><AppIcon name="clock" :size="12" />{{ formatDateTime(alert.created_at) }}</span>
              <span>{{ relativeTime(alert.created_at) }}</span>
              <span v-if="alert.acked_by" class="acked-by">由 {{ alert.acked_by }} 于 {{ relativeTime(alert.acked_at) }}确认</span>
            </div>
          </div>

          <div v-if="canAck && alert.status === 'open'" class="alert-actions">
            <button class="btn btn-sm btn-teal" type="button" :disabled="ackingId === alert.id" @click="ackOne(alert)">
              <span v-if="ackingId === alert.id" class="spinner" />
              <AppIcon v-else name="check" :size="13" />
              确认
            </button>
          </div>
        </article>
      </div>
      <div v-else class="empty">
        <div class="empty-icon"><AppIcon name="check" :size="20" /></div>
        {{ statusFilter === 'open' ? '当前无待确认告警，系统运行平稳' : '当前筛选条件下暂无告警' }}
      </div>
    </section>
  </div>
</template>

<style scoped>
.meta-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-3);
}

.level-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.level-card {
  text-align: left;
  padding: 14px 16px;
  color: var(--text);
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.level-card:hover {
  transform: translateY(-2px);
}

.level-card.active {
  border-color: var(--border-accent);
  box-shadow: 0 0 0 1px var(--border-accent);
}

.level-top {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--text-2);
}

.level-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
}

.level-total {
  margin-left: auto;
  font-size: 10px;
}

.level-count {
  display: block;
  font-family: var(--font-display);
  font-size: 27px;
  font-weight: 700;
  line-height: 1.3;
  margin-top: 3px;
}

.level-note {
  font-size: 10px;
  color: var(--text-3);
}

.level-card.tone-fatal .level-dot,
.level-card.tone-critical .level-dot {
  background: var(--danger);
  box-shadow: 0 0 0 4px var(--danger-soft);
}

.level-card.tone-fatal .level-count,
.level-card.tone-critical .level-count {
  color: var(--danger);
}

.level-card.tone-warning .level-dot {
  background: var(--warning);
}

.level-card.tone-warning .level-count {
  color: var(--warning);
}

.level-card.tone-info .level-dot {
  background: var(--blue);
}

.level-card.tone-info .level-count {
  color: var(--blue);
}

.alert-head {
  flex-wrap: wrap;
}

.alert-head .toolbar {
  flex: 1;
  justify-content: flex-end;
}

.seg-count {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.7;
}

.search-box {
  width: 230px;
}

.alert-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 42px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.alert-list {
  display: flex;
  flex-direction: column;
}

.alert-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--border);
  border-left: 2px solid transparent;
  transition: background-color 0.15s ease;
}

.alert-row:last-child {
  border-bottom: 0;
}

.alert-row:hover {
  background: color-mix(in srgb, var(--panel-strong) 55%, transparent);
}

.alert-row.selected {
  background: var(--accent-soft);
}

.alert-row.tone-fatal,
.alert-row.tone-critical {
  border-left-color: var(--danger);
}

.alert-row.tone-warning {
  border-left-color: var(--warning);
}

.alert-row.tone-info {
  border-left-color: var(--blue);
}

.alert-row.acked {
  border-left-color: var(--border);
  opacity: 0.72;
}

.check-box {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1px solid var(--border-strong);
  background: var(--panel-inset);
  color: #1a1206;
  display: grid;
  place-items: center;
  flex: none;
  margin-top: 3px;
  transition: all 0.16s ease;
}

.check-box.on {
  background: var(--accent);
  border-color: var(--accent);
}

.check-placeholder {
  width: 18px;
  flex: none;
}

.alert-body {
  flex: 1;
  min-width: 0;
}

.alert-headline {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}

.alert-code {
  font-size: 10px;
  color: var(--text-3);
}

.alert-body h3 {
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text);
  margin-bottom: 3px;
}

.alert-body p {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.65;
}

.alert-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 7px;
  font-size: 10.5px;
  color: var(--text-3);
}

.alert-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.acked-by {
  color: var(--success);
}

.alert-actions {
  flex: none;
  display: flex;
  align-items: center;
}

@media (max-width: 1023px) {
  .level-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .level-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .level-count {
    font-size: 22px;
  }
  .alert-head {
    flex-direction: column;
    align-items: stretch;
  }
  .alert-head .toolbar {
    flex-wrap: wrap;
  }
  .search-box {
    width: 100%;
  }
  .alert-row {
    padding: 13px 14px;
    flex-wrap: wrap;
  }
  .alert-actions {
    width: 100%;
    justify-content: flex-end;
    padding-left: 30px;
  }
  .alert-meta {
    gap: 8px;
  }
}
</style>
