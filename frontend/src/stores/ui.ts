import { defineStore } from 'pinia'

export type Theme = 'dark' | 'light'
export type ToastTone = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: number
  tone: ToastTone
  title: string
  message?: string
}

const THEME_KEY = 'lisa_theme'
const SIDEBAR_KEY = 'lisa_sidebar_collapsed'

function initialTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY)
  return stored === 'light' ? 'light' : 'dark'
}

let toastSeed = 0

export const useUiStore = defineStore('ui', {
  state: () => ({
    theme: initialTheme() as Theme,
    sidebarCollapsed: localStorage.getItem(SIDEBAR_KEY) === '1',
    mobileNavOpen: false,
    commandOpen: false,
    toasts: [] as Toast[],
    routeLoading: false,
  }),
  getters: {
    isDark: (state) => state.theme === 'dark',
  },
  actions: {
    applyTheme() {
      document.documentElement.dataset.theme = this.theme
      const meta = document.querySelector('meta[name="theme-color"]')
      if (meta) meta.setAttribute('content', this.theme === 'dark' ? '#070d17' : '#edf1f7')
    },
    setTheme(theme: Theme) {
      this.theme = theme
      localStorage.setItem(THEME_KEY, theme)
      this.applyTheme()
    },
    toggleTheme() {
      this.setTheme(this.theme === 'dark' ? 'light' : 'dark')
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
      localStorage.setItem(SIDEBAR_KEY, this.sidebarCollapsed ? '1' : '0')
    },
    openMobileNav() {
      this.mobileNavOpen = true
      document.body.style.overflow = 'hidden'
    },
    closeMobileNav() {
      this.mobileNavOpen = false
      document.body.style.overflow = ''
    },
    toast(tone: ToastTone, title: string, message?: string, duration = 4200) {
      const id = ++toastSeed
      this.toasts.push({ id, tone, title, message })
      window.setTimeout(() => this.dismissToast(id), duration)
    },
    success(title: string, message?: string) {
      this.toast('success', title, message)
    },
    error(title: string, message?: string) {
      this.toast('error', title, message, 6000)
    },
    warning(title: string, message?: string) {
      this.toast('warning', title, message, 5200)
    },
    info(title: string, message?: string) {
      this.toast('info', title, message)
    },
    dismissToast(id: number) {
      this.toasts = this.toasts.filter((toast) => toast.id !== id)
    },
  },
})
