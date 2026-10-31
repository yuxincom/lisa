export interface NavItem {
  title: string
  path: string
  icon: string
  permission: string
  description: string
  badge?: 'alerts' | 'approvals' | 'changes'
  mobile?: boolean
}

export interface NavSection {
  title: string
  items: NavItem[]
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: '决策层',
    items: [
      {
        title: '指挥驾驶舱',
        path: '/dashboard',
        icon: 'dashboard',
        permission: 'dashboard:read',
        description: '全厂排产 KPI、基线、告警与审批态势',
        mobile: true,
      },
      {
        title: '智能排产',
        path: '/gantt',
        icon: 'gantt',
        permission: 'plans:read',
        description: '资源甘特、冻结窗口与 A/B/C 方案对比',
        mobile: true,
      },
      {
        title: '方案审批',
        path: '/plans',
        icon: 'approval',
        permission: 'plans:read',
        description: '白盒归因、硬约束校验与电子签名终审',
        badge: 'approvals',
        mobile: true,
      },
    ],
  },
  {
    title: '协同执行',
    items: [
      {
        title: '变更影响',
        path: '/changes',
        icon: 'change',
        permission: 'changes:read',
        description: '涟漪推演、影响面量化与协同重排',
        badge: 'changes',
        mobile: true,
      },
      {
        title: '齐套检查',
        path: '/kits',
        icon: 'kits',
        permission: 'kits:read',
        description: '九要素 × 三时点齐套校验与缺口处置',
      },
      {
        title: '智能体中心',
        path: '/agents',
        icon: 'agents',
        permission: 'agents:read',
        description: 'C/M/A 三级智能体运行与 ReAct 追溯',
      },
      {
        title: '订单台账',
        path: '/orders',
        icon: 'orders',
        permission: 'plans:read',
        description: '订单进度、工艺路线与交期风险',
      },
    ],
  },
  {
    title: '数据与知识',
    items: [
      {
        title: '数据基座',
        path: '/data',
        icon: 'data',
        permission: 'data:read',
        description: '五维点检门禁、数据源健康与覆盖度',
      },
      {
        title: '知识规则',
        path: '/knowledge',
        icon: 'knowledge',
        permission: 'knowledge:read',
        description: '68 条规则、137 项约束与专识检索',
      },
    ],
  },
  {
    title: '治理监督',
    items: [
      {
        title: '审计追溯',
        path: '/audit',
        icon: 'audit',
        permission: 'audit:read',
        description: 'SHA-256 哈希链、PROV-O 血缘与操作回放',
      },
      {
        title: '告警中心',
        path: '/alerts',
        icon: 'alerts',
        permission: 'alerts:read',
        description: '分级告警、确认处置与升级链路',
        badge: 'alerts',
        mobile: true,
      },
      {
        title: '系统设置',
        path: '/settings',
        icon: 'settings',
        permission: 'settings:read',
        description: '目标权重、冻结窗口、安全策略与用户',
      },
    ],
  },
]

export const ALL_NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items)

export const MOBILE_NAV = ALL_NAV_ITEMS.filter((item) => item.mobile)
