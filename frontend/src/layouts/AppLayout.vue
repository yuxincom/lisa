<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dashboardApi } from '@/api'
import { ALL_NAV_ITEMS, MOBILE_NAV, NAV_SECTIONS } from '@/router/nav'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { formatDate, formatTime } from '@/utils/format'
import AppIcon from '@/components/AppIcon.vue'
import AppLogo from '@/components/AppLogo.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import CommandPalette from '@/components/CommandPalette.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const now = ref(new Date())
const alertCount = ref(0)
const approvalCount = ref(0)
const changeCount = ref(0)
const qualityScore = ref<number | null>(null)
const version = ref('1.0.0')
const userMenuOpen = ref(false)
const shellLoading = ref(false)
let clockTimer: number | undefined
let shellTimer: number | undefined

const activePath = computed(() => route.path)
const currentSection = computed(
  () => NAV_SECTIONS.find((section) => section.items.some((item) => activePath.value.startsWith(item.path)))?.title || '工作台',
)
const pageTitle = computed(() => (route.meta.title as string) || '工作台')
const isMobileNavVisible = computed(() => MOBILE_NAV.every((item) => auth.can(item.permission)))

const shift = computed(() => {
  const hour = now.value.getHours()
  return hour >= 8 && hour < 20 ? { label: '白班', time: '08:00 – 20:00' } : { label: '夜班', time: '20:00 – 08:00' }
})

const initials = computed(() => {
  const name = auth.user?.name || auth.user?.username || '?'
  return name.replace(/[·\s]/g, '').slice(-2)
})

const avatarStyle = computed(() => ({
  background: auth.user?.avatar_color
    ? `linear-gradient(145deg, ${auth.user.avatar_color}, color-mix(in srgb, ${auth.user.avatar_color} 55%, #0a1322))`
    : 'linear-gradient(145deg, #f0a43a, #4fd1c5)',
}))

const alertBadge = computed(() => (alertCount.value > 99 ? '99+' : String(alertCount.value)))

function navBadge(item: { badge?: string }) {
  if (item.badge === 'alerts') return alertCount.value
  if (item.badge === 'approvals') return approvalCount.value
  if (item.badge === 'changes') return changeCount.value
  return 0
}

function isActive(path: string) {
  return activePath.value === path || activePath.value.startsWith(`${path}/`)
}

function visibleNav(section: (typeof NAV_SECTIONS)[number]) {
  return section.items.filter((item) => auth.can(item.permission))
}

async function loadShell() {
  if (!auth.can('dashboard:read')) return
  shellLoading.value = true
  try {
    const data = await dashboardApi.overview()
    alertCount.value = data.alert_counts.fatal + data.alert_counts.critical + data.alert_counts.warning
    approvalCount.value = data.approvals?.length || 0
    changeCount.value = (data.changes || []).filter((change) => change.status !== '已关闭' && change.status !== '已挂起').length
    qualityScore.value = data.quality?.overall ?? null
    version.value = String(data.system?.version || '1.0.0')
  } catch {
    // shell indicators degrade silently; page content surfaces the real error
  } finally {
    shellLoading.value = false
  }
}

function onUnauthorized() {
  auth.clear()
  if (route.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: route.fullPath } })
  }
}

function onRefreshShell() {
  void loadShell()
}

async function handleLogout() {
  userMenuOpen.value = false
  await auth.logout()
  router.replace({ name: 'login' })
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target.closest('.user-area')) userMenuOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    ui.commandOpen = !ui.commandOpen
  }
}

watch(
  () => route.path,
  () => {
    ui.closeMobileNav()
    userMenuOpen.value = false
  },
)

onMounted(() => {
  ui.applyTheme()
  void loadShell()
  clockTimer = window.setInterval(() => (now.value = new Date()), 30000)
  shellTimer = window.setInterval(() => void loadShell(), 90000)
  window.addEventListener('lisa:unauthorized', onUnauthorized)
  window.addEventListener('lisa:refresh-shell', onRefreshShell)
  document.addEventListener('click', onDocumentClick)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (clockTimer) window.clearInterval(clockTimer)
  if (shellTimer) window.clearInterval(shellTimer)
  window.removeEventListener('lisa:unauthorized', onUnauthorized)
  window.removeEventListener('lisa:refresh-shell', onRefreshShell)
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': ui.sidebarCollapsed }">
    <!-- Desktop sidebar -->
    <aside class="sidebar hide-mobile">
      <div class="sidebar-head">
        <AppLogo :collapsed="ui.sidebarCollapsed" />
      </div>

      <nav class="sidebar-nav" aria-label="主导航">
        <div v-for="section in NAV_SECTIONS" :key="section.title" class="nav-section">
          <div v-if="!ui.sidebarCollapsed" class="nav-section-title">{{ section.title }}</div>
          <div v-else class="nav-section-line" />
          <RouterLink
            v-for="item in visibleNav(section)"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: isActive(item.path) }"
            :title="ui.sidebarCollapsed ? item.title : undefined"
          >
            <span class="nav-icon"><AppIcon :name="item.icon" :size="17" /></span>
            <template v-if="!ui.sidebarCollapsed">
              <span class="nav-label">{{ item.title }}</span>
              <span v-if="navBadge(item)" class="nav-badge">{{ navBadge(item) > 99 ? '99+' : navBadge(item) }}</span>
            </template>
            <span v-else-if="navBadge(item)" class="nav-dot" />
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div v-if="!ui.sidebarCollapsed" class="shield-card">
          <div class="shield-top">
            <span class="shield-icon"><AppIcon name="shield" :size="15" /></span>
            <span class="shield-title">写保护网关</span>
            <span class="dot dot-live" />
          </div>
          <div class="shield-meta">
            <span>L0 门禁 {{ qualityScore !== null ? qualityScore.toFixed(1) + '%' : '—' }}</span>
            <span class="mono">v{{ version }}</span>
          </div>
          <div class="shield-bar"><i :style="{ width: `${qualityScore ?? 0}%` }" /></div>
        </div>
        <div v-else class="shield-mini" title="写保护网关运行中">
          <span class="dot dot-live" />
        </div>
        <button class="collapse-btn" type="button" :aria-label="ui.sidebarCollapsed ? '展开侧栏' : '收起侧栏'" @click="ui.toggleSidebar">
          <AppIcon :name="ui.sidebarCollapsed ? 'chevronRight' : 'chevronLeft'" :size="15" />
          <span v-if="!ui.sidebarCollapsed">收起导航</span>
        </button>
      </div>
    </aside>

    <!-- Mobile drawer -->
    <Teleport to="body">
      <Transition name="mobile-nav">
        <div v-if="ui.mobileNavOpen" class="mobile-nav-root">
          <div class="mobile-nav-overlay" @click="ui.closeMobileNav()" />
          <aside class="mobile-nav-panel">
            <div class="mobile-nav-head">
              <AppLogo />
              <button class="icon-btn" aria-label="关闭菜单" @click="ui.closeMobileNav()">
                <AppIcon name="close" :size="18" />
              </button>
            </div>
            <div class="mobile-nav-body">
              <div v-for="section in NAV_SECTIONS" :key="section.title" class="nav-section">
                <div class="nav-section-title">{{ section.title }}</div>
                <RouterLink
                  v-for="item in visibleNav(section)"
                  :key="item.path"
                  :to="item.path"
                  class="nav-item"
                  :class="{ active: isActive(item.path) }"
                >
                  <span class="nav-icon"><AppIcon :name="item.icon" :size="18" /></span>
                  <span class="nav-label">{{ item.title }}</span>
                  <span v-if="navBadge(item)" class="nav-badge">{{ navBadge(item) }}</span>
                </RouterLink>
              </div>
            </div>
            <div class="mobile-nav-foot">
              <div class="flex items-center gap-10">
                <span class="avatar" :style="avatarStyle">{{ initials }}</span>
                <div class="grow">
                  <div class="fs-13" style="font-weight: 620">{{ auth.displayName }}</div>
                  <div class="muted fs-12">{{ auth.roleLabel || auth.user?.role_label }}</div>
                </div>
                <ThemeToggle />
              </div>
              <button class="btn btn-ghost btn-block" style="margin-top: 12px" @click="handleLogout">
                <AppIcon name="logout" :size="15" /> 退出登录
              </button>
            </div>
          </aside>
        </div>
      </Transition>
    </Teleport>

    <div class="main-column">
      <header class="topbar">
        <div class="topbar-left">
          <button class="icon-btn only-mobile" aria-label="打开导航" @click="ui.openMobileNav()">
            <AppIcon name="menu" :size="19" />
          </button>
          <div class="topbar-title">
            <div class="crumbs">
              <span>{{ currentSection }}</span>
              <AppIcon name="chevronRight" :size="12" />
              <span class="crumb-current">{{ pageTitle }}</span>
            </div>
            <div class="topbar-page">{{ pageTitle }}</div>
          </div>
        </div>

        <div class="topbar-right">
          <button class="command-trigger hide-mobile" type="button" @click="ui.commandOpen = true">
            <AppIcon name="search" :size="15" />
            <span>搜索订单 / 方案 / 事件</span>
            <kbd>Ctrl K</kbd>
          </button>

          <div class="shift-pill hide-mobile">
            <span class="shift-dot" :class="{ night: shift.label === '夜班' }" />
            <span>{{ shift.label }}</span>
            <span class="muted mono">{{ shift.time }}</span>
          </div>

          <div class="clock hide-mobile">
            <div class="clock-time num">{{ formatTime(now.toISOString()) }}</div>
            <div class="clock-date">{{ formatDate(now.toISOString()) }}</div>
          </div>

          <ThemeToggle />

          <RouterLink to="/alerts" class="icon-btn bell-btn" aria-label="告警中心">
            <AppIcon name="alerts" :size="18" />
            <span v-if="alertCount" class="bell-count">{{ alertBadge }}</span>
          </RouterLink>

          <div class="user-area">
            <button class="user-trigger" type="button" @click.stop="userMenuOpen = !userMenuOpen">
              <span class="avatar" :style="avatarStyle">{{ initials }}</span>
              <span class="user-copy hide-mobile">
                <span class="user-name">{{ auth.displayName }}</span>
                <span class="user-role">{{ auth.roleLabel || auth.user?.role_label }}</span>
              </span>
              <AppIcon name="chevronDown" :size="13" class="hide-mobile" />
            </button>
            <Transition name="dropdown">
              <div v-if="userMenuOpen" class="user-menu">
                <div class="user-menu-head">
                  <div class="fs-13" style="font-weight: 650">{{ auth.displayName }}</div>
                  <div class="muted fs-12">{{ auth.user?.department || '生产计划部' }} · {{ auth.user?.clearance }}</div>
                </div>
                <RouterLink to="/settings" class="user-menu-item">
                  <AppIcon name="settings" :size="15" /> 系统设置
                </RouterLink>
                <RouterLink to="/audit" class="user-menu-item">
                  <AppIcon name="audit" :size="15" /> 审计追溯
                </RouterLink>
                <div class="user-menu-divider" />
                <button class="user-menu-item danger" type="button" @click="handleLogout">
                  <AppIcon name="logout" :size="15" /> 退出登录
                </button>
              </div>
            </Transition>
          </div>
        </div>
      </header>

      <main class="content">
        <RouterView v-slot="{ Component }">
          <Transition name="view" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>

    <!-- Mobile bottom navigation -->
    <nav v-if="isMobileNavVisible" class="bottom-nav" aria-label="快捷导航">
      <RouterLink
        v-for="item in MOBILE_NAV"
        :key="item.path"
        :to="item.path"
        class="bottom-item"
        :class="{ active: isActive(item.path) }"
      >
        <span class="bottom-icon">
          <AppIcon :name="item.icon" :size="19" />
          <span v-if="item.badge === 'alerts' && alertCount" class="bottom-dot" />
        </span>
        <span>{{ item.title.replace('指挥', '') }}</span>
      </RouterLink>
      <button class="bottom-item" type="button" @click="ui.openMobileNav()">
        <span class="bottom-icon"><AppIcon name="more" :size="19" /></span>
        <span>更多</span>
      </button>
    </nav>

    <CommandPalette />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

/* ---------- Sidebar ---------- */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-deep) 88%, transparent);
  border-right: 1px solid var(--border);
  backdrop-filter: blur(20px);
  z-index: 40;
  transition: width 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}

.sidebar::after {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 140px;
  background: radial-gradient(240px 130px at 30% 0%, rgba(240, 164, 58, 0.07), transparent 70%);
  pointer-events: none;
}

.sidebar-collapsed .sidebar {
  width: var(--sidebar-w-collapsed);
}

.sidebar-head {
  padding: 18px 17px 15px;
  border-bottom: 1px solid var(--border);
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 12px 10px 16px;
  scrollbar-width: thin;
}

.nav-section {
  margin-bottom: 10px;
}

.nav-section-title {
  padding: 10px 10px 6px;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-3);
}

.nav-section-line {
  height: 1px;
  margin: 9px 10px;
  background: var(--border);
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 0 10px;
  margin-bottom: 2px;
  border-radius: 9px;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 520;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.nav-item:hover {
  background: color-mix(in srgb, var(--panel-strong) 62%, transparent);
  color: var(--text);
}

.nav-item.active {
  color: var(--text);
  background: linear-gradient(90deg, rgba(240, 164, 58, 0.13), rgba(240, 164, 58, 0.02));
  box-shadow: inset 0 0 0 1px rgba(240, 164, 58, 0.16);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 9px;
  bottom: 9px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, var(--accent), var(--teal));
  box-shadow: 0 0 10px var(--accent-line);
}

.nav-icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: none;
  color: var(--text-3);
  transition: color 0.16s ease;
}

.nav-item:hover .nav-icon,
.nav-item.active .nav-icon {
  color: var(--accent);
}

.nav-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 99px;
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 32%, transparent);
  display: grid;
  place-items: center;
  font-size: 9.5px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.nav-dot {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-soft);
}

.sidebar-collapsed .nav-item {
  justify-content: center;
  padding: 0;
}

.sidebar-collapsed .nav-section {
  margin-bottom: 4px;
}

.sidebar-foot {
  padding: 12px 12px 14px;
  border-top: 1px solid var(--border);
}

.shield-card {
  padding: 10px 11px 9px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: linear-gradient(140deg, rgba(61, 220, 151, 0.06), transparent 70%);
  margin-bottom: 8px;
}

.shield-top {
  display: flex;
  align-items: center;
  gap: 7px;
}

.shield-icon {
  display: grid;
  place-items: center;
  width: 21px;
  height: 21px;
  border-radius: 6px;
  color: var(--success);
  background: var(--success-soft);
}

.shield-title {
  flex: 1;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-2);
}

.shield-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 7px 0 5px;
  font-size: 9.5px;
  color: var(--text-3);
}

.shield-bar {
  height: 3px;
  border-radius: 99px;
  background: var(--panel-inset);
  overflow: hidden;
}

.shield-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--success), var(--teal));
  transition: width 0.8s ease;
}

.shield-mini {
  display: grid;
  place-items: center;
  padding: 8px 0 10px;
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 30px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-3);
  font-size: 11.5px;
  transition: all 0.16s ease;
}

.collapse-btn:hover {
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--panel-strong);
}

/* ---------- Main column ---------- */
.main-column {
  flex: 1;
  min-width: 0;
  margin-left: var(--sidebar-w);
  transition: margin-left 0.26s cubic-bezier(0.22, 1, 0.36, 1);
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.sidebar-collapsed .main-column {
  margin-left: var(--sidebar-w-collapsed);
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: var(--topbar-h);
  padding: 0 clamp(16px, 2.4vw, 30px);
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 78%, transparent);
  backdrop-filter: blur(20px);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.topbar-title {
  min-width: 0;
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}

.crumb-current {
  color: var(--text-2);
  font-weight: 600;
}

.topbar-page {
  display: none;
  font-size: 15px;
  font-weight: 680;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 9px;
}

.command-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 10px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  color: var(--text-3);
  font-size: 12px;
  transition: all 0.16s ease;
  min-width: 220px;
}

.command-trigger:hover {
  border-color: var(--border-strong);
  color: var(--text-2);
}

.command-trigger kbd {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 9.5px;
  padding: 2px 5px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--panel-strong);
  color: var(--text-3);
}

.shift-pill {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 10px;
  border-radius: 99px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  font-size: 10.5px;
  color: var(--text-2);
  white-space: nowrap;
}

.shift-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.shift-dot.night {
  background: var(--violet);
  box-shadow: 0 0 0 3px var(--violet-soft);
}

.clock {
  text-align: right;
  line-height: 1.15;
  min-width: 74px;
}

.clock-time {
  font-size: 14px;
  font-weight: 680;
  letter-spacing: 0.02em;
}

.clock-date {
  font-size: 9.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.icon-btn {
  position: relative;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  transition: all 0.16s ease;
  flex: none;
}

.icon-btn:hover {
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--panel-strong);
}

.bell-btn {
  color: var(--text-2);
}

.bell-count {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 99px;
  background: var(--danger);
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  display: grid;
  place-items: center;
  border: 2px solid var(--bg);
  font-variant-numeric: tabular-nums;
}

.user-area {
  position: relative;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 5px 3px 3px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  transition: all 0.16s ease;
}

.user-trigger:hover {
  border-color: var(--border);
  background: var(--panel-inset);
}

.avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  color: #fff;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  flex: none;
}

.user-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  text-align: left;
}

.user-name {
  font-size: 12px;
  font-weight: 620;
  color: var(--text);
}

.user-role {
  font-size: 9.5px;
  color: var(--text-3);
  margin-top: 1px;
}

.user-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 220px;
  padding: 6px;
  border-radius: 12px;
  border: 1px solid var(--border-strong);
  background: var(--panel-solid);
  box-shadow: var(--shadow);
  z-index: 50;
}

.user-menu-head {
  padding: 9px 10px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 5px;
}

.user-menu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  text-align: left;
  transition: all 0.15s ease;
}

.user-menu-item:hover {
  background: var(--panel-strong);
  color: var(--text);
}

.user-menu-item.danger {
  color: var(--danger);
}

.user-menu-item.danger:hover {
  background: var(--danger-soft);
}

.user-menu-divider {
  height: 1px;
  background: var(--border);
  margin: 5px 0;
}

.content {
  flex: 1;
  min-width: 0;
}

/* ---------- Mobile drawer ---------- */
.mobile-nav-root {
  position: fixed;
  inset: 0;
  z-index: 1300;
}

.mobile-nav-overlay {
  position: absolute;
  inset: 0;
  background: rgba(3, 8, 16, 0.62);
  backdrop-filter: blur(4px);
}

.mobile-nav-panel {
  position: absolute;
  inset: 0 auto 0 0;
  width: min(322px, 88vw);
  display: flex;
  flex-direction: column;
  background: var(--panel-solid);
  border-right: 1px solid var(--border-strong);
  box-shadow: 22px 0 70px rgba(0, 0, 0, 0.4);
}

.mobile-nav-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 14px;
  border-bottom: 1px solid var(--border);
}

.mobile-nav-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px 16px;
}

.mobile-nav-foot {
  padding: 14px 16px calc(14px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--border);
}

.mobile-nav-enter-active,
.mobile-nav-leave-active {
  transition: opacity 0.25s ease;
}

.mobile-nav-enter-active .mobile-nav-panel,
.mobile-nav-leave-active .mobile-nav-panel {
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.mobile-nav-enter-from,
.mobile-nav-leave-to {
  opacity: 0;
}

.mobile-nav-enter-from .mobile-nav-panel,
.mobile-nav-leave-to .mobile-nav-panel {
  transform: translateX(-100%);
}

/* ---------- Bottom nav ---------- */
.bottom-nav {
  position: fixed;
  left: 10px;
  right: 10px;
  bottom: calc(10px + env(safe-area-inset-bottom));
  z-index: 35;
  display: none;
  padding: 7px 4px;
  border-radius: 17px;
  border: 1px solid var(--border-strong);
  background: color-mix(in srgb, var(--panel-solid) 90%, transparent);
  backdrop-filter: blur(20px);
  box-shadow: 0 16px 44px rgba(0, 0, 0, 0.36);
}

.bottom-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  border: 0;
  background: transparent;
  color: var(--text-3);
  font-size: 9.5px;
  padding: 4px 2px;
  border-radius: 11px;
  transition: color 0.16s ease;
}

.bottom-icon {
  position: relative;
  display: grid;
  place-items: center;
  width: 34px;
  height: 25px;
  border-radius: 8px;
  transition: all 0.18s ease;
}

.bottom-item.active {
  color: var(--accent);
}

.bottom-item.active .bottom-icon {
  background: var(--accent-soft);
}

.bottom-dot {
  position: absolute;
  top: 1px;
  right: 4px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--danger);
}

/* ---------- Transitions ---------- */
.view-enter-active,
.view-leave-active {
  transition: opacity 0.18s ease, transform 0.2s ease;
}

.view-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.view-leave-to {
  opacity: 0;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.16s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

@media (max-width: 1023px) {
  .main-column {
    margin-left: var(--sidebar-w);
  }
  .crumbs {
    display: none;
  }
  .topbar-page {
    display: block;
  }
  .command-trigger {
    width: 34px;
    min-width: 0;
    padding: 0;
    justify-content: center;
  }
  .command-trigger span,
  .command-trigger kbd {
    display: none;
  }
  .shift-pill,
  .clock {
    display: none;
  }
  .user-trigger .hide-mobile {
    display: none !important;
  }
}

@media (max-width: 767px) {
  .main-column,
  .sidebar-collapsed .main-column {
    margin-left: 0;
  }
  .topbar {
    height: 58px;
    padding: 0 12px;
  }
  .bottom-nav {
    display: flex;
  }
  .topbar-right {
    gap: 6px;
  }
  .topbar-right > .theme-toggle {
    display: none;
  }
  .shift-pill {
    display: none;
  }
  .user-trigger {
    padding: 2px;
  }
  .avatar {
    width: 30px;
    height: 30px;
    border-radius: 8px;
  }
  .bell-btn {
    width: 32px;
    height: 32px;
  }
}
</style>
