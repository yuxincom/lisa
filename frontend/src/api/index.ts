import { downloadFile, http, query } from './client'
import type {
  AgentCatalog,
  AgentRun,
  Alert,
  AuditLog,
  AuditStats,
  Change,
  ChangeImpact,
  CoverageResponse,
  DashboardOverview,
  KitCheck,
  KitOverview,
  KnowledgeCatalog,
  KnowledgeItem,
  LoginResponse,
  MetaInfo,
  Order,
  OrderDetail,
  Paginated,
  PendingBatch,
  Plan,
  PlanItem,
  QualityResponse,
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
    http.post<AgentRun>('/agents/run', { scenario, change_id: changeId ?? null, options }),
  runs: (params: { agent_code?: string; scenario?: string; limit?: number } = {}) =>
    http.get<Paginated<AgentRun>>(`/agents/runs${query(params)}`),
  runDetail: (id: number) => http.get<AgentRun>(`/agents/runs/${id}`),
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
    http.get<Paginated<KitCheck> & { counts: Record<string, number>; checkpoint: string; checkpoint_label: string }>(
      `/kits${query(params)}`,
    ),
  check: (orderId: number, checkpoint: string) =>
    http.post<KitCheck>('/kits/check', { order_id: orderId, checkpoint }),
  detail: (orderId: number) =>
    http.get<{ order: Pick<Order, 'id' | 'order_no' | 'product_name' | 'priority' | 'kit_status' | 'due_date'>; checkpoints: KitCheck[] }>(
      `/kits/${orderId}`,
    ),
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
    http.get<{ ok: boolean; total: number; broken_at: number | null; last_hash: string; algorithm: string; verified_at: string }>(
      '/audit/verify',
    ),
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
    }>('/orders/summary'),
  list: (params: { status?: string; priority?: string; search?: string; limit?: number; offset?: number } = {}) =>
    http.get<Paginated<Order>>(`/orders${query(params)}`),
  detail: (id: number) => http.get<OrderDetail>(`/orders/${id}`),
}

export const systemApi = {
  meta: () => http.get<MetaInfo>('/system/meta'),
  settings: () => http.get<{ values: SettingsValues; scenarios: Record<string, import('@/types').ScenarioMeta> }>('/system/settings'),
  updateSettings: (values: SettingsValues) =>
    http.put<{ values: SettingsValues; updated: string[] }>('/system/settings', { values }),
  users: () => http.get<Paginated<User>>('/system/users'),
  security: () => http.get<SecurityInfo>('/system/security'),
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
}

export type { ChangeImpact }
