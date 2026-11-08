const pad = (value: number) => String(value).padStart(2, '0')

export function parseDate(value?: string | null): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value?: string | null, fallback = '—'): string {
  const date = parseDate(value)
  if (!date) return fallback
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatDate(value?: string | null, fallback = '—'): string {
  const date = parseDate(value)
  if (!date) return fallback
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function formatTime(value?: string | null, fallback = '—'): string {
  const date = parseDate(value)
  if (!date) return fallback
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatMonthDay(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return '—'
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function relativeTime(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return '—'
  const diff = Date.now() - date.getTime()
  const minutes = Math.round(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatDate(value)
}

export function formatNumber(value: number | undefined | null, digits = 0): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatPercent(value: number | undefined | null, digits = 0): string {
  if (value === undefined || value === null) return '—'
  return `${value.toFixed(digits)}%`
}

export function formatHours(minutes: number | undefined | null): string {
  if (!minutes) return '0h'
  if (minutes < 60) return `${Math.round(minutes)}min`
  const hours = minutes / 60
  if (hours < 48) return `${hours.toFixed(1)}h`
  return `${(hours / 24).toFixed(1)}d`
}

export function truncateMiddle(text: string | undefined | null, head = 8, tail = 6): string {
  if (!text) return '—'
  if (text.length <= head + tail + 3) return text
  return `${text.slice(0, head)}…${text.slice(-tail)}`
}

export const SCENARIO_LABEL: Record<string, string> = {
  A: 'A · 交期优先',
  B: 'B · 瓶颈均衡',
  C: 'C · 换型成本',
}

export const SCENARIO_NOTE: Record<string, string> = {
  A: '军品保供 · 交期优先',
  B: '瓶颈保护 · 负荷平滑',
  C: '换型优化 · 成本优先',
}

export const DOMAIN_COLOR: Record<string, string> = {
  锻造: '#f0a43a',
  机加: '#5b9dff',
  热表: '#ff7a7a',
  钣焊: '#b48bff',
  装配: '#4fd1c5',
  试车: '#f6c445',
  大修: '#7f93f5',
}

export const DOMAINS = ['锻造', '机加', '热表', '钣焊', '装配', '试车', '大修']

export const PRIORITY_LABEL: Record<string, string> = {
  P0: 'P0 · 军品急件',
  P1: 'P1 · 重点',
  P2: 'P2 · 常规',
}

export const RISK_LABEL: Record<string, string> = {
  normal: '正常',
  tight: '紧张',
  late: '逾期',
  blocked: '阻断',
}

export const CHANGE_TYPE_LABEL: Record<string, string> = {
  fault: '设备故障',
  insert: '紧急插单',
  material: '物料缺料',
  rework: '返工返修',
  order_change: '订单变更',
  inspection: '检测军检',
  ecn: '工艺变更',
}

export const SEVERITY_LABEL: Record<string, string> = {
  fatal: '致命',
  critical: '严重',
  warning: '警告',
  info: '提示',
}

export const ALERT_TYPE_LABEL: Record<string, string> = {
  equipment: '设备',
  kit: '齐套',
  approval: '审批',
  data: '数据',
  change: '变更',
  special: '特殊过程',
  plan: '排产',
  audit: '审计',
  bottleneck: '瓶颈',
  quality: '质量',
  system: '系统',
}

export const AGENT_LEVEL_LABEL: Record<string, string> = {
  C: '化合物级',
  M: '分子级',
  A: '原子级',
}

export function statusTone(status?: string | null): string {
  switch (status) {
    case 'applied':
    case 'approved':
    case 'succeeded':
    case 'online':
    case '齐套':
    case '已签发':
    case 'success':
      return 'success'
    case 'pending':
    case '评估中':
    case 'running':
    case '执行中':
    case '待审批':
      return 'warning'
    case 'rejected':
    case 'blocked':
    case 'fatal':
    case 'critical':
    case '缺项':
    case '缺料':
    case '阻断':
    case '逾期':
    case 'degraded':
      return 'danger'
    case 'superseded':
    case '已关闭':
    case '已完工':
    case '待接入':
      return 'muted'
    case 'expired':
      return 'muted'
    case 'open':
      return 'warning'
    case 'acked':
      return 'success'
    default:
      return 'blue'
  }
}

export function alertTone(level?: string): string {
  switch (level) {
    case 'fatal':
    case 'critical':
      return 'danger'
    case 'warning':
      return 'warning'
    case 'info':
      return 'blue'
    default:
      return 'muted'
  }
}

export function actionLabel(action?: string): string {
  const map: Record<string, string> = {
    'auth.login': '登录',
    'auth.logout': '登出',
    'plan.approve': '方案签发',
    'plan.reject': '方案驳回',
    'plan.feedback': '人机反馈',
    'plan.signature.failed': '签名失败',
    'agent.run': '智能体运行',
    'change.create': '创建扰动',
    'change.assess': '影响评估',
    'change.plans.generate': '生成方案',
    'change.resolve': '关闭事件',
    'kit.check': '齐套检查',
    'alert.ack': '告警确认',
    'audit.verify': '审计校验',
    'write.blocked': '写保护拦截',
    'data.check': '数据点检',
    'settings.update': '参数变更',
    'system.write_shield.test': '写保护演练',
  }
  return map[action || ''] || action || '—'
}

export function shortRole(role?: string): string {
  const map: Record<string, string> = {
    admin: '管理员',
    commander: '指挥部',
    planner: '计划员',
    dispatcher: '调度员',
    engineer: '工艺员',
    expert: '专家',
  }
  return map[role || ''] || role || '—'
}

export function pct(part: number, total: number): number {
  if (!total) return 0
  return Math.round((part / total) * 1000) / 10
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function dayKey(value: string | Date): string {
  const date = typeof value === 'string' ? parseDate(value) : value
  if (!date) return ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function minutesBetween(start: string, end: string): number {
  const a = parseDate(start)
  const b = parseDate(end)
  if (!a || !b) return 0
  return Math.max(0, (b.getTime() - a.getTime()) / 60000)
}
