import { downloadFile, http, query } from './client'
import type {
  AgentCatalog,
  AgentRun,
  Alert,
  AnchorRecord,
  AnchorStatus,
  AuditLog,
  AuditStats,
  BackupCreated,
  BackupOverview,
  BackupVerified,
  Change,
  ChangeImpact,
  CoverageResponse,
  DashboardOverview,
  AdapterOverview,
  AdapterRunResult,
  KitCheck,
  KitOverview,
  KitSourceFreshness,
  Job,
  KnowledgeCatalog,
  KnowledgeItem,
  LlmConfig,
  LlmStatus,
  LlmTestResult,
  LoginResponse,
  McpCatalog,
  MetaInfo,
  Order,
  OrderDetail,
  Paginated,
  PendingBatch,
  Plan,
  PlanItem,
  QualityResponse,
  QueueHealth,
  Resource,
  Rule,
  SecurityInfo,
  SettingsValues,
  User,
} from '@/types'

export const authApi = {
  login: (username: string, password: string) =>
    http.post<LoginResponse>('/auth/login', { username, password }),
  me: () => http.get<{ user: User; permissions: string[]; role_label: string }>('/auth/me'),
  logout: () => http.post<{ ok: boolean }>('/auth/logout'),
}

export const dashboardApi = {
  overview: () => http.get<DashboardOverview>('/dashboard/overview'),
}

export const plansApi = {
  list: (params: { status?: string; type?: string; include_history?: boolean; limit?: number; offset?: number } = {}) =>
    http.get<Paginated<Plan> & { counts: Record<string, number> }>(`/plans${query(params)}`),
  pendingBatches: () => http.get<{ items: PendingBatch[]; total: number }>('/plans/batches/pending'),
  baseline: () => http.get<Plan>('/plans/baseline'),
  detail: (id: number, includeItems = false) =>
    http.get<Plan>(`/plans/${id}${query({ include_items: includeItems })}`),
  gantt: (id: number, params: { domain?: string; search?: string; priority?: string } = {}) =>
    http.get<{
      plan: Plan
      domain: string
      items: PlanItem[]
      baseline_items: PlanItem[]
      resources: Resource[]
      freeze_until: string
      now: string
      stats: { operations: number; orders: number; late: number; tight: number; locked: number; resources: number; bottleneck: number }
      domains: string[]
    }>(`/plans/${id}/gantt${query(params)}`),
  items: (id: number, params: { domain?: string; search?: string; risk?: string; limit?: number; offset?: number } = {}) =>
    http.get<Paginated<PlanItem>>(`/plans/${id}/items${query(params)}`),
  approve: (id: number, payload: { plan_id: number; action: 'approve' | 'reject'; comment?: string; password: string }) =>
    http.post<{ ok: boolean; action: string; plan: Plan; message?: string; apply?: Record<string, unknown> }>(`/plans/${id}/approve`, payload),
  writeAttempt: (id: number) => http.post<never>(`/plans/${id}/write-attempt`),
  lineage: (id: number) =>
    http.get<{
      nodes: { id: string; label: string; type: string; meta: Record<string, unknown> }[]
      edges: { source: string; target: string; label: string }[]
      prov: { bundle: string; hard_checks: number; hard_failed: number; soft_violations: number; trace_version: string }
    }>(`/plans/${id}/lineage`),
  feedback: (id: number, accepted: boolean, note = '') =>
    http.post<{ ok: boolean; message: string }>(`/plans/${id}/feedback`, { plan_id: id, accepted, note }),
}

export const agentsApi = {
  catalog: () => http.get<AgentCatalog>('/agents/catalog'),
  run: (scenario: string, changeId?: number | null, options: Record<string, unknown> = {}) =>
    http.post<{ job: Job; run: AgentRun | null }>('/agents/run', { scenario, change_id: changeId ?? null, options }),
  runs: (params: { agent_code?: string; scenario?: string; limit?: number } = {}) =>
    http.get<Paginated<AgentRun>>(`/agents/runs${query(params)}`),
  runDetail: (id: number) => http.get<AgentRun>(`/agents/runs/${id}`),
  llm: () => http.get<LlmStatus>('/agents/llm'),
  saveLlm: (values: Partial<LlmConfig>) =>
    http.put<{ config: LlmConfig; credential_present: boolean }>('/agents/llm', { values }),
  testLlm: (values: Partial<LlmConfig>) => http.post<LlmTestResult>('/agents/llm/test', { values }),
}

export const jobsApi = {
  list: (params: { status?: string; kind?: string; limit?: number } = {}) =>
    http.get<Paginated<Job> & { hidden_by_clearance: number; clearance_enabled: boolean }>(`/jobs${query(params)}`),
  get: (id: number) => http.get<Job>(`/jobs/${id}`),
  health: () => http.get<QueueHealth>('/jobs/health'),
  cancel: (id: number) => http.post<Job>(`/jobs/${id}/cancel`),
}

export const mcpApi = {
  tools: () => http.get<McpCatalog>('/mcp/tools'),
  call: (name: string, args: Record<string, unknown> = {}) =>
    http.post<{ tool: string; content: { type: string; text: string }[]; isError: boolean; structured: unknown; latency_ms: number }>(
      `/mcp/tools/${name}/call`,
      { arguments: args },
    ),
}

export const changesApi = {
  summary: () =>
    http.get<{
      total: number
      open: number
      critical: number
      counts: { status: string; count: number }[]
      types: { type: string; count: number }[]
      sla_minutes: number
      sla_target: string
      hidden_by_clearance?: number
      clearance_enabled?: boolean
    }>('/changes/summary'),
  list: (params: { status?: string; type?: string; search?: string; limit?: number } = {}) =>
    http.get<Paginated<Change>>(`/changes${query(params)}`),
  detail: (id: number) => http.get<Change>(`/changes/${id}`),
  create: (payload: { type: string; title: string; detail: string; severity: string; payload?: Record<string, unknown> }) =>
    http.post<Change>('/changes', payload),
  assess: (id: number) => http.post<Change>(`/changes/${id}/assess`),
  plans: (id: number) =>
    http.post<{ change: Change; plans: Plan[] }>(`/changes/${id}/plans`, { scenario: 'A' }),
  resolve: (id: number) => http.post<Change>(`/changes/${id}/resolve`),
}

export const kitsApi = {
  overview: () => http.get<KitOverview>('/kits/overview'),
  list: (params: { checkpoint?: string; status?: string; search?: string; limit?: number } = {}) =>
    http.get<Paginated<KitCheck> & {
      counts: Record<string, number>;
      checkpoint: string;
      checkpoint_label: string;
      hidden_orders_by_clearance?: number;
    }>(
      `/kits${query(params)}`,
    ),
  check: (orderId: number, checkpoint: string) =>
    http.post<KitCheck>('/kits/check', { order_id: orderId, checkpoint }),
  detail: (orderId: number) =>
    http.get<{
      order: Pick<Order, 'id' | 'order_no' | 'product_name' | 'priority' | 'kit_status' | 'due_date' | 'clearance'>;
      checkpoints: KitCheck[];
    }>(`/kits/${orderId}`),
}

export const dataApi = {
  quality: () => http.get<QualityResponse>('/data/quality'),
  sources: () => http.get<Paginated<QualityResponse['sources'][number]>>('/data/sources'),
  coverage: () => http.get<CoverageResponse>('/data/coverage'),
  check: () => http.post<QualityResponse>('/data/quality/check'),
  source: (id: number) => http.get<QualityResponse['sources'][number] & { events: AuditLog[] }>(`/data/sources/${id}`),
}

export const knowledgeApi = {
  catalog: () => http.get<KnowledgeCatalog>('/knowledge/catalog'),
  items: (params: { category?: string; q?: string; limit?: number } = {}) =>
    http.get<Paginated<KnowledgeItem>>(`/knowledge/items${query(params)}`),
  search: (q: string, topK = 8) =>
    http.post<{ query: string; items: KnowledgeItem[]; hits: number; mode: string; note: string }>('/knowledge/search', {
      query: q,
      top_k: topK,
    }),
  rule: (code: string) => http.get<Rule>(`/knowledge/rules/${code}`),
}

export const auditApi = {
  stats: () => http.get<AuditStats>('/audit/stats'),
  verify: () =>
    http.get<{
      ok: boolean
      total: number
      broken_at: number | null
      last_hash: string
      algorithm: string
      verified_at: string
      tamper_evident?: boolean
      anchor?: AnchorStatus
    }>('/audit/verify'),
  anchor: () => http.post<AnchorRecord>('/audit/anchor'),
  anchors: () => http.get<AnchorStatus>('/audit/anchors'),
  list: (params: { action?: string; result?: string; limit?: number; offset?: number; actor?: string } = {}) =>
    http.get<Paginated<AuditLog>>(`/audit${query(params)}`),
  detail: (id: number) => http.get<AuditLog & { prev_log: AuditLog | null }>(`/audit/${id}`),
}

export const alertsApi = {
  summary: () =>
    http.get<{
      total: number
      open: number
      acked: number
      levels: { level: string; count: number }[]
      open_levels: { level: string; count: number }[]
    }>('/alerts/summary'),
  list: (params: { level?: string; status?: string; type?: string; search?: string; limit?: number } = {}) =>
    http.get<Paginated<Alert>>(`/alerts${query(params)}`),
  ack: (ids: number[]) => http.post<{ ok: boolean; acked: number }>('/alerts/ack', { alert_ids: ids }),
  ackOne: (id: number) => http.post<Alert | { ok: boolean }>(`/alerts/${id}/ack`),
}

export const ordersApi = {
  summary: () =>
    http.get<{
      total: number
      by_status: { status: string; count: number }[]
      by_priority: { priority: string; count: number }[]
      military: number
      kit_risk: number
      hidden_by_clearance?: number
      hidden_by_level?: Record<string, number>
      clearance_levels?: string[]
      clearance_enabled?: boolean
      hidden_by_plant?: Record<string, number>
      plants?: string[]
      plants_enabled?: boolean
      your_plants?: string[] | null
    }>('/orders/summary'),
  list: (params: { status?: string; priority?: string; plant?: string; search?: string; limit?: number; offset?: number } = {}) =>
    http.get<Paginated<Order> & { hidden_by_plant?: number }>(`/orders${query(params)}`),
  detail: (id: number) => http.get<OrderDetail>(`/orders/${id}`),
}

export const systemApi = {
  meta: () => http.get<MetaInfo>('/system/meta'),
  settings: () => http.get<{ values: SettingsValues; scenarios: Record<string, import('@/types').ScenarioMeta> }>('/system/settings'),
  updateSettings: (values: Partial<SettingsValues>) =>
    http.put<{ values: SettingsValues; updated: string[] }>('/system/settings', { values }),
  users: () => http.get<Paginated<User> & { plants: string[] }>('/system/users'),
  updateUserScope: (username: string, values: { plants: string[]; clearance?: string }) =>
    http.put<User>(`/system/users/${username}/scope`, values),
  security: () => http.get<SecurityInfo>('/system/security'),
  backups: () => http.get<BackupOverview>('/system/backups'),
  createBackup: () => http.post<BackupCreated>('/system/backups'),
  verifyBackup: (name: string) => http.post<BackupVerified>('/system/backups/verify', { name }),
  writeShieldTest: () => http.post<{ blocked: boolean; message: string; audit: string }>('/system/write-shield/test'),
  search: (q: string) =>
    http.get<{
      query: string
      orders: { id: number; title: string; subtitle: string; status: string; priority: string }[]
      plans: { id: number; title: string; subtitle: string; status: string; code: string }[]
      changes: { id: number; title: string; subtitle: string; status: string; code: string }[]
    }>(`/system/search${query({ q })}`),
  stats: () =>
    http.get<{
      orders: number
      operations: number
      resources: number
      plans: number
      rules: number
      agent_runs: number
      alerts: number
      audit_logs: number
      db_engine: string
    }>('/system/stats'),
  exportOrders: () => downloadFile('/system/export/orders.csv', 'LISA-orders.csv'),
  exportAudit: () => downloadFile('/system/export/audit.csv', 'LISA-audit.csv'),
  kitSources: () => http.get<Record<string, KitSourceFreshness>>('/system/main-data/kit-sources'),
  adapters: () => http.get<AdapterOverview>('/system/main-data/adapters'),
  runAdapters: (force = true) => http.post<AdapterRunResult>('/system/main-data/adapters/run', { force }),
}

export type { ChangeImpact }
