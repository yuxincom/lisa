<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { auditApi, systemApi } from '@/api'
import { errorMessage } from '@/composables/useAsync'
import { useUiStore } from '@/stores/ui'
import type { AuditLog, AuditStats } from '@/types'
import {
  actionLabel,
  formatDateTime,
  shortRole,
  statusTone,
  truncateMiddle,
} from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import BaseDrawer from '@/components/BaseDrawer.vue'

interface VerifyResult {
  ok: boolean
  total: number
  broken_at: number | null
  last_hash: string
  algorithm: string
  verified_at: string
}

const PAGE_SIZE = 100
const RESULT_OPTIONS = [
  { key: '', label: '全部结果' },
  { key: 'success', label: '成功' },
  { key: 'denied', label: '越权拒绝' },
  { key: 'blocked', label: '写保护拦截' },
  { key: 'failed', label: '失败' },
]

const ui = useUiStore()

const stats = ref<AuditStats | null>(null)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const offset = ref(0)
const loading = ref(false)
const error = ref('')
const actionFilter = ref('')
const resultFilter = ref('')
const search = ref('')
const verifying = ref(false)
const verifyResult = ref<VerifyResult | null>(null)
const exporting = ref(false)

const detailOpen = ref(false)
const activeLog = ref<AuditLog | null>(null)
const prevLog = ref<{ seq: number; hash: string; ts: string } | null>(null)

const actionOptions = computed(() => stats.value?.actions || [])
const resultLabel = (result: string) =>
  RESULT_OPTIONS.find((item) => item.key === result)?.label || result || '—'
const canLoadMore = computed(() => logs.value.length < total.value)
const chainPrev = computed(() => logs.value[0]?.prev_hash || stats.value?.last_hash || '')

function resultTone(result: string) {
  const tone = statusTone(result)
  if (result === 'denied' || result === 'blocked') return 'danger'
  if (result === 'failed') return 'warning'
  return tone === 'blue' ? 'success' : tone
}

async function loadStats() {
  try {
    stats.value = await auditApi.stats()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadLogs(reset = true) {
  loading.value = true
  error.value = ''
  try {
    if (reset) {
      offset.value = 0
      logs.value = []
    }
    const res = await auditApi.list({
      action: actionFilter.value || undefined,
      result: resultFilter.value || undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
    })
    const items = (res.items || []).filter((log) => {
      if (!search.value.trim()) return true
      const keyword = search.value.trim().toLowerCase()
      return `${log.action} ${log.actor} ${log.target_id} ${log.target_type}`.toLowerCase().includes(keyword)
    })
    logs.value = reset ? items : [...logs.value, ...items]
    total.value = res.total || 0
    offset.value = logs.value.length
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function filterChanged() {
  loadLogs(true)
}

async function verify() {
  verifying.value = true
  try {
    verifyResult.value = await auditApi.verify()
    if (verifyResult.value.ok) {
      ui.success('哈希链校验通过', `共校验 ${verifyResult.value.total} 条审计记录`)
    } else {
      ui.error('哈希链校验失败', `断链位置 seq=${verifyResult.value.broken_at}`)
    }
  } catch (err) {
    ui.error('校验失败', errorMessage(err))
  } finally {
    verifying.value = false
  }
}

async function openDetail(log: AuditLog) {
  activeLog.value = log
  detailOpen.value = true
  prevLog.value = null
  try {
    const res = await auditApi.detail(log.id)
    prevLog.value = res.prev_log
  } catch {
    // prev link is optional context
  }
}

async function exportLogs() {
  exporting.value = true
  try {
    await systemApi.exportAudit()
    ui.success('审计导出已生成', 'CSV 文件已开始下载')
  } catch (err) {
    ui.error('导出失败', errorMessage(err))
  } finally {
    exporting.value = false
  }
}

function formatDetail(detail: Record<string, unknown>) {
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), loadLogs(true)])
  verify()
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="L6 · 审计与追溯"
      title="不可篡改审计链"
      subtitle="SHA-256 哈希链 · PROV-O 血缘 · 军工审计留存 · 全量操作可回放"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" :disabled="exporting" @click="exportLogs">
          <span v-if="exporting" class="spinner" />
          <AppIcon v-else name="download" :size="15" />
          导出 CSV
        </button>
        <button class="btn btn-primary" type="button" :disabled="verifying" @click="verify">
          <span v-if="verifying" class="spinner" />
          <AppIcon v-else name="shield" :size="15" />
          {{ verifying ? '校验中…' : '校验哈希链' }}
        </button>
      </template>
      <template #meta>
        <span>记录 {{ stats?.total ?? '—' }} 条</span>
        <span class="meta-dot" />
        <span>最近写入 {{ formatDateTime(stats?.last_ts) }}</span>
      </template>
    </PageHeader>

    <div class="audit-hero">
      <section class="panel chain-panel">
        <div class="panel-head">
          <div class="panel-title">
            <span class="title-mark" />
            哈希链完整性
            <StatusBadge
              v-if="verifyResult"
              :label="verifyResult.ok ? '校验通过' : '断链'"
              :tone="verifyResult.ok ? 'success' : 'danger'"
            />
          </div>
          <span class="panel-sub">{{ verifyResult?.algorithm || 'SHA-256 哈希链' }}</span>
        </div>
        <div class="panel-body chain-body">
          <div class="chain-flow">
            <div class="chain-node genesis">
              <span class="chain-label">GENESIS</span>
              <code class="hash">0000…0000</code>
            </div>
            <span class="chain-arrow"><AppIcon name="chevrons" :size="16" /></span>
            <div class="chain-node">
              <span class="chain-label">PREV HASH</span>
              <code class="hash">{{ truncateMiddle(chainPrev, 12, 10) }}</code>
            </div>
            <span class="chain-arrow"><AppIcon name="chevrons" :size="16" /></span>
            <div class="chain-node current">
              <span class="chain-label">LAST HASH</span>
              <code class="hash">{{ truncateMiddle(verifyResult?.last_hash || stats?.last_hash, 12, 10) }}</code>
            </div>
          </div>
          <div class="chain-meta">
            <div>
              <span>校验记录</span>
              <strong class="num">{{ verifyResult?.total ?? stats?.total ?? '—' }}</strong>
            </div>
            <div>
              <span>断链位置</span>
              <strong class="num" :class="{ 'text-danger': verifyResult?.broken_at }">
                {{ verifyResult?.broken_at ? `seq ${verifyResult.broken_at}` : '无' }}
              </strong>
            </div>
            <div>
              <span>最近校验</span>
              <strong>{{ formatDateTime(verifyResult?.verified_at) }}</strong>
            </div>
            <div>
              <span>存储策略</span>
              <strong>WORM · 只追加</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="panel action-panel">
        <div class="panel-head">
          <div class="panel-title"><span class="title-mark" />操作分布</div>
          <span class="panel-sub">Top {{ actionOptions.length }}</span>
        </div>
        <div class="panel-body action-body">
          <button
            v-for="item in actionOptions"
            :key="item.action"
            type="button"
            class="action-row"
            :class="{ active: actionFilter === item.action }"
            @click="actionFilter = actionFilter === item.action ? '' : item.action; filterChanged()"
          >
            <span class="action-name">{{ actionLabel(item.action) }}</span>
            <strong class="num">{{ item.count }}</strong>
          </button>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-head audit-head">
        <div class="panel-title"><span class="title-mark" />审计日志</div>
        <div class="toolbar">
          <div class="search-box">
            <AppIcon name="search" :size="14" />
            <input v-model="search" class="input" placeholder="操作人 / 对象 / 动作" @input="filterChanged" />
          </div>
          <select v-model="resultFilter" class="select result-select" @change="filterChanged">
            <option v-for="option in RESULT_OPTIONS" :key="option.key" :value="option.key">{{ option.label }}</option>
          </select>
          <select v-model="actionFilter" class="select action-select" @change="filterChanged">
            <option value="">全部动作</option>
            <option v-for="item in actionOptions" :key="item.action" :value="item.action">
              {{ actionLabel(item.action) }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="error" class="empty">
        <AppIcon name="alert" :size="22" />
        {{ error }}
      </div>
      <div v-else class="table-wrap">
        <table class="data-table audit-table">
          <thead>
            <tr>
              <th>Seq</th>
              <th>时间</th>
              <th>操作人</th>
              <th>角色</th>
              <th>动作</th>
              <th>对象</th>
              <th>结果</th>
              <th>密级</th>
              <th>Hash</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id" class="click-row" @click="openDetail(log)">
              <td class="num mono seq-cell">{{ log.seq }}</td>
              <td class="time-cell">{{ formatDateTime(log.ts) }}</td>
              <td class="cell-strong">{{ log.actor }}</td>
              <td>{{ shortRole(log.role) }}</td>
              <td>{{ actionLabel(log.action) }}</td>
              <td class="target-cell">
                <span class="mono">{{ log.target_type }}:{{ log.target_id }}</span>
              </td>
              <td>
                <StatusBadge :label="resultLabel(log.result)" :tone="resultTone(log.result)" />
              </td>
              <td>
                <span class="badge badge-muted">{{ log.clearance }}</span>
              </td>
              <td class="hash">{{ truncateMiddle(log.hash, 8, 6) }}</td>
              <td>
                <button class="btn btn-ghost btn-sm" type="button" @click.stop="openDetail(log)">
                  <AppIcon name="eye" :size="13" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!logs.length && !loading && !error" class="empty">暂无审计记录</div>
      <div v-if="loading" class="audit-loading"><span class="spinner" /> 正在读取审计链…</div>
      <div v-if="canLoadMore && !loading" class="panel-foot load-more">
        <span>已加载 {{ logs.length }} / {{ total }} 条</span>
        <button class="btn btn-ghost btn-sm" type="button" @click="loadLogs(false)">加载更多</button>
      </div>
    </section>

    <BaseDrawer
      :model-value="detailOpen"
      width="620px"
      :title="activeLog ? `审计记录 #${activeLog.seq}` : '审计详情'"
      :subtitle="activeLog ? `${actionLabel(activeLog.action)} · ${formatDateTime(activeLog.ts)}` : ''"
      @update:model-value="detailOpen = false"
    >
      <template v-if="activeLog">
        <div class="detail-badges">
          <StatusBadge :label="resultLabel(activeLog.result)" :tone="resultTone(activeLog.result)" />
          <span class="badge badge-muted">{{ shortRole(activeLog.role) }}</span>
          <span class="badge badge-muted">密级 {{ activeLog.clearance }}</span>
        </div>
        <div class="kv"><span class="k">操作人</span><span class="v">{{ activeLog.actor }}</span></div>
        <div class="kv"><span class="k">动作</span><span class="v">{{ actionLabel(activeLog.action) }} <span class="mono muted">({{ activeLog.action }})</span></span></div>
        <div class="kv"><span class="k">对象</span><span class="v mono">{{ activeLog.target_type }}:{{ activeLog.target_id }}</span></div>
        <div class="kv"><span class="k">时间</span><span class="v">{{ formatDateTime(activeLog.ts) }}</span></div>
        <div class="kv"><span class="k">结果</span><span class="v">{{ resultLabel(activeLog.result) }}</span></div>

        <h4 class="section-title">哈希链定位</h4>
        <div class="hash-block">
          <span class="hash-label">PREV HASH</span>
          <code class="hash">{{ activeLog.prev_hash }}</code>
          <span class="hash-link"><AppIcon name="link" :size="13" /> {{ prevLog ? `seq ${prevLog.seq} · ${formatDateTime(prevLog.ts)}` : '前序记录不可用' }}</span>
          <span class="hash-label">CURRENT HASH</span>
          <code class="hash">{{ activeLog.hash }}</code>
        </div>

        <h4 class="section-title">操作详情</h4>
        <div class="code-block detail-json">{{ formatDetail(activeLog.detail) }}</div>
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

.audit-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.chain-body {
  padding: 20px 22px;
}

.chain-flow {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.chain-node {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
  min-width: 150px;
}

.chain-node.genesis {
  border-style: dashed;
}

.chain-node.current {
  border-color: var(--accent-line);
  box-shadow: 0 0 0 1px var(--accent-line);
}

.chain-label {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--text-3);
}

.chain-node .hash {
  font-size: 10.5px;
  color: var(--text-2);
}

.chain-node.current .hash {
  color: var(--accent);
}

.chain-arrow {
  color: var(--text-3);
}

.chain-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.chain-meta div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.chain-meta span {
  font-size: 10.5px;
  color: var(--text-3);
}

.chain-meta strong {
  font-size: 12.5px;
  color: var(--text);
  font-weight: 600;
}

.action-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 12px;
  max-height: 210px;
  overflow-y: auto;
}

.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  text-align: left;
  transition: all 0.15s ease;
}

.action-row:hover {
  background: var(--panel-inset);
}

.action-row.active {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}

.action-row strong {
  font-size: 12px;
}

.audit-head {
  flex-wrap: wrap;
}

.audit-head .toolbar {
  flex: 1;
  justify-content: flex-end;
}

.search-box {
  width: 220px;
}

.result-select {
  width: 130px;
}

.action-select {
  width: 150px;
}

.seq-cell {
  color: var(--text-3);
  font-size: 11px;
}

.time-cell {
  white-space: nowrap;
  font-size: 11.5px;
}

.target-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.click-row {
  cursor: pointer;
}

.audit-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.load-more {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.detail-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  margin: 18px 0 8px;
}

.hash-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-inset);
}

.hash-label {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--text-3);
  margin-top: 4px;
}

.hash-label:first-child {
  margin-top: 0;
}

.hash-link {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--text-3);
}

.detail-json {
  max-height: 320px;
  font-size: 11px;
}

@media (max-width: 1023px) {
  .audit-hero {
    grid-template-columns: 1fr;
  }
  .chain-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .action-body {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .action-row {
    flex: 1;
    min-width: 140px;
  }
}

@media (max-width: 767px) {
  .audit-head {
    flex-direction: column;
    align-items: stretch;
  }
  .audit-head .toolbar {
    flex-wrap: wrap;
  }
  .search-box {
    width: 100%;
  }
  .result-select,
  .action-select {
    flex: 1;
    width: auto;
  }
  .chain-flow {
    flex-direction: column;
    align-items: stretch;
  }
  .chain-arrow {
    align-self: center;
    transform: rotate(90deg);
  }
  .chain-node {
    min-width: 0;
  }
  .chain-meta {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
