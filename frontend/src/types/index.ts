export interface User {
  id: number
  username: string
  name: string
  role: string
  role_label: string
  clearance: string
  department: string
  avatar_color: string
}

export interface LoginResponse {
  token: string
  token_type: string
  expires_in_hours: number
  user: User
  permissions: string[]
  role_label: string
}

export interface Kpi {
  key: string
  label: string
  value: number
  unit: string
  target: number
  target_label: string
  higher_better: boolean
  status: string
  spark: number[]
  note: string
}

export interface ApprovalInfo {
  id: number
  status: string
  approver_name: string | null
  deadline: string | null
  minutes_left: number | null
  escalated: boolean
  comment: string | null
  signature: string | null
  decided_at: string | null
}

export interface HardCheck {
  code: string
  title: string
  description: string
  passed: boolean
  count: number
  samples: string[]
}

export interface SoftViolation {
  code: string
  title: string
  severity: string
  count: number
  message: string
  samples: string[]
}

export interface PlanSummary {
  orders: number
  operations: number
  domains: { name: string; count: number }[]
  resources: number
  p0_orders: number
  kit_risk: number
  late_orders: number
  locked_operations: number
  objective: string
  reasoning: string[]
  hard_checks: HardCheck[]
  soft_violations: SoftViolation[]
  generated_by: string
  solver: string
  algorithm: string
}

export interface PlanKpi {
  orders: number
  operations: number
  late_orders: number
  tight_orders: number
  on_time_rate: number
  predicted_adoption: number
  accuracy: number
  avg_utilization: number
  bottleneck_utilization: number
  changeover_minutes: number
  changeover_count: number
  risk_operations: number
  makespan_hours: number
  locked_operations: number
  total_labor_hours: number
  objective_scores: Record<string, number>
  total_score: number
  weights: Record<string, number>
}

export interface DiffSample {
  operation_id: number
  order_no: string
  name: string
  seq: number
  domain: string
  from_start: string
  to_start: string
  delta_hours: number
  resource_changed: boolean
  from_resource: number
  to_resource: number
}

export interface PlanDiff {
  moved: number
  added: number
  unchanged: number
  total: number
  samples: DiffSample[]
}

export interface Plan {
  id: number
  code: string
  name: string
  type: string
  status: string
  status_label: string
  scenario: string
  objective: string
  weights: Record<string, number>
  summary: PlanSummary
  kpi: PlanKpi
  diff: PlanDiff
  created_by: string
  created_at: string
  submitted_at: string | null
  approved_at: string | null
  applied_at: string | null
  baseline: boolean
  batch_id: string | null
  change_id: number | null
  approval: ApprovalInfo | null
  items_count?: number
  items?: PlanItem[]
  change?: Change | null
  siblings?: { id: number; code: string; scenario: string; objective: string; status: string; score: number; on_time_rate: number }[]
}

export interface PlanItem {
  id: number
  order_id: number
  operation_id: number
  order_no: string
  product_name: string
  priority: string
  seq: number
  name: string
  domain: string
  resource_id: number
  resource_code: string
  resource_name: string
  start: string
  end: string
  duration_minutes: number
  setup_minutes: number
  risk: string
  risk_label: string
  locked: boolean
  reason: string
}

export interface Resource {
  id: number
  code: string
  name: string
  domain: string
  plant: string
  capacity_hours: number
  efficiency: number
  bottleneck: boolean
  status: string
  maintenance_until: string | null
}

export interface Alert {
  id: number
  code: string
  level: string
  level_label: string
  type: string
  title: string
  message: string
  source: string
  related_type: string
  related_id: string
  status: string
  created_at: string
  acked_by: string | null
  acked_at: string | null
}

export interface Approval extends Plan {}

export interface PendingBatch {
  batch_id: string
  change_id: number | null
  type: string
  created_at: string
  plans: Plan[]
  recommended: string
}

export interface DashboardOverview {
  kpis: Kpi[]
  baseline: {
    id: number
    code: string
    objective: string
    applied_at: string
    kpi: PlanKpi
    summary: PlanSummary
  } | null
  alerts: Alert[]
  alert_counts: Record<string, number>
  approvals: Plan[]
  pending_batches: number
  resource_load: {
    resource: string
    code: string
    domain: string
    load: number
    hours: number
    bottleneck: boolean
    status: string
  }[]
  domain_workload: { domain: string; operations: number; hours: number; late: number; load: number }[]
  order_status: { status: string; count: number }[]
  plan_status: Record<string, number>
  quality: {
    overall: number
    threshold: number
    dimensions: { key: string; label?: string; score: number; passed: boolean }[]
    gate: { passed: boolean; label: string; message: string }
  } | null
  kit: {
    by_checkpoint: { checkpoint: string; label: string; total: number; passed: number; rate: number; missing: number; blocked: number }[]
    post_schedule_rate: number
    gap_owners: { owner: string; count: number }[]
    updated_at: string
  } | null
  changes: Change[]
  risk_orders: {
    order_id: number
    order_no: string
    product_name: string
    priority: string
    due_date: string
    scheduled_finish: string
    late_hours: number
  }[]
  recent_runs: {
    code: string
    agent_code: string
    summary: string
    status: string
    level: string
    started_at: string
    simulated_minutes: number
  }[]
  audit_tail: AuditLog[]
  system: Record<string, string | number>
  escalated_now: number
}

export interface Agent {
  code: string
  name: string
  level: string
  level_label: string
  duty: string
  permission: string
  skills: string[]
  status: string
  runs: number
  success_rate: number
  avg_minutes: number
  last_run_at: string | null
  last_summary: string | null
}

export interface AgentStep {
  index: number
  phase: string
  title: string
  thought: string
  action: string
  observation: string
  duration_ms: number
  status: string
}

export interface AgentRun {
  id: number
  code: string
  agent_code: string
  agent_name: string
  level: string
  scenario: string
  status: string
  summary: string
  operator: string
  started_at: string
  ended_at: string
  duration_ms: number
  plan_id: number | null
  output: Record<string, unknown>
  steps?: AgentStep[]
  plans?: Plan[]
}

export interface AgentCatalog {
  levels: { level: string; label: string; count: number }[]
  agents: Agent[]
  recent_runs: AgentRun[]
  summary: { total: number; active: number; online: number; total_runs: number }
}

export interface Change {
  id: number
  code: string
  type: string
  title: string
  detail: string
  severity: string
  status: string
  occurred_at: string
  payload: Record<string, unknown>
  impact?: ChangeImpact | null
  options?: { plans: ChangePlanOption[] } | { plans: [] }
  resolved_at: string | null
  reporter: string
}

export interface ChangePlanOption {
  plan_id: number
  code: string
  scenario: string
  objective: string
  score: number
  on_time_rate: number
  late_orders: number
}

export interface ChangeImpact {
  summary: {
    affected_orders: number
    affected_operations: number
    critical_orders: number
    avg_delay_days: number
    max_late_days: number
    projected_delay_hours: number
    domains: { name: string; orders: number }[]
    resource: string
    sla_minutes: number
    elapsed_minutes: number
    confidence: number
    assessed_at: string
    engine: string
  }
  affected_orders: {
    order_id: number
    order_no: string
    product_name: string
    priority: string
    due_date: string
    current_finish: string
    projected_finish: string
    late_days: number
    domains: string[]
    operations: number
    status: string
    kit_status: string
  }[]
  graph: {
    nodes: { id: string; label: string; type: string; level: number; meta: Record<string, unknown> }[]
    edges: { source: string; target: string; kind: string }[]
  }
  timeline: { time: string; text: string }[]
  recommendation: string
}

export interface KitElement {
  key: string
  name: string
  source: string
  status: string
  critical: boolean
  value: string
  action?: string
}

export interface KitCheck {
  id: number
  order_id: number
  order_no: string
  product_name: string
  priority?: string
  checkpoint: string
  checkpoint_label: string
  status: string
  score: number
  elements: KitElement[]
  gaps: { key: string; name: string; reason: string; action: string; owner: string; due_hours: number; critical: boolean }[]
  checked_at: string
}

export interface KitOverview {
  by_checkpoint: { checkpoint: string; label: string; total: number; passed: number; rate: number; missing: number; blocked: number }[]
  post_schedule_rate: number
  gap_owners: { owner: string; count: number }[]
  updated_at: string
}

export interface QualityDimension {
  key: string
  label: string
  description: string
  source: string
  score: number
  threshold: number
  passed: boolean
  detail: { issues: number; fields: string[]; sample: string }
  checked_at: string
  trend: { date: string; score: number }[]
}

export interface DataSource {
  id: number
  code: string
  name: string
  type: string
  status: string
  latency_ms: number
  last_sync: string
  records: number
  quality: number
  owner: string
}

export interface QualityResponse {
  dimensions: QualityDimension[]
  overall: number
  threshold: number
  gate: { passed: boolean; label: string; message: string }
  sources: DataSource[]
  checked_at: string
}

export interface CoverageResponse {
  datasets: { code: string; name: string; current: number; target: number; unit: string; status: string; note: string }[]
  phases: { name: string; count: number; accuracy: string; complete: boolean }[]
  interface_count: number
  mapping_count: number
  product_count: number
  operation_count: number
  resources: number
  annotation: {
    templates: number
    fields: number
    minimum_set: number
    expert_confirm_rate: number
    kappa: number
  }
}

export interface Rule {
  id: number
  code: string
  kind: string
  category: string
  title: string
  description: string
  priority: number
  trigger: string
  action: string
  weight: number
  domain: string
  enabled: boolean
  hits: number
}

export interface KnowledgeItem {
  id: number
  code: string
  category: string
  title: string
  content: string
  source_ref: string
  trace_version: string
  tags: string[]
  confidence: number
  kind?: string
  score?: number
}

export interface KnowledgeCatalog {
  summary: {
    total: number
    rules: number
    hard: number
    soft: number
    enabled: number
    categories: { name: string; count: number }[]
    knowledge_items: number
    dataset_scale: { general: number; expert: number; phase2: number }
  }
  rules: Rule[]
  hard_constraints: Rule[]
  soft_constraints: Rule[]
}

export interface AuditLog {
  id: number
  seq: number
  ts: string
  actor: string
  role: string
  action: string
  target_type: string
  target_id: string
  result: string
  prev_hash: string
  hash: string
  clearance: string
  detail: Record<string, unknown>
}

export interface AuditStats {
  total: number
  last_hash: string
  last_ts: string
  actions: { action: string; count: number }[]
}

export interface SecurityInfo {
  write_shield: { enabled: boolean; policy: string; blocked_writes: number; target: string; status: string }
  abac: {
    matrix: { role: string; label: string; permissions: string[]; permission_labels?: string[]; count?: number }[]
    denied_events: number
    policy_engine: string
    target: string
  }
  audit: { hash_chain: string; worm: boolean; retention: string }
  encryption: { transport: string; desensitization: string; data_boundary: string }
  electronic_signature: { levels: string[]; algorithm: string }
}

export interface SettingsValues {
  weights: Record<string, number>
  thresholds: Record<string, number>
  freeze_days: number
  shift: { start: number; end: number; days: number }
  approval_timeout_minutes: number
  solver_timeout_seconds: number
  auto_escalate?: boolean
  write_shield?: boolean
  [key: string]: unknown
}

export interface ScenarioMeta {
  code: string
  objective: string
  weights: Record<string, number>
}

export interface MetaInfo {
  name: string
  name_en: string
  version: string
  environment: string
  roles: { code: string; label: string }[]
  domains?: string[]
  scenarios?: Record<string, ScenarioMeta>
  constraints?: { hard?: string | number; soft?: string | number; rules?: number; [key: string]: unknown }
  kpis?: { key: string; label: string; target: string }[]
  compliance?: { title?: string; detail?: string; [key: string]: unknown }[]
  architecture?: { layer: string; name: string; detail: string }[]
}

export interface Order {
  id: number
  order_no: string
  product_id: number
  product_name: string
  qty: number
  priority: string
  plant: string
  customer: string
  due_date: string
  status: string
  progress: number
  is_military: boolean
  kit_status: string
  created_at: string
  released_at: string
  scheduled_start?: string | null
  scheduled_finish?: string | null
  scheduled_operations?: number
  late_hours?: number
  risk?: string
}

export interface OrderDetail {
  order: Order
  operations: {
    id: number
    seq: number
    name: string
    domain: string
    special: boolean
    status: string
    std_minutes: number
    setup_minutes: number
    planned_start: string | null
    planned_end: string | null
    resource: string | null
    locked: boolean
    risk: string
  }[]
  kits: KitCheck[]
}

export interface Paginated<T> {
  items: T[]
  total: number
  limit?: number
  offset?: number
}
