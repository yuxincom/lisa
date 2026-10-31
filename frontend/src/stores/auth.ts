import { defineStore } from 'pinia'
import { authApi } from '@/api'
import { getToken, setToken } from '@/api/client'
import type { User } from '@/types'

const USER_KEY = 'lisa_user'

function readUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: readUser(),
    permissions: [] as string[],
    roleLabel: '',
    loading: false,
    initialized: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isAdmin: (state) => state.user?.role === 'admin',
    displayName: (state) => state.user?.name || state.user?.username || '未登录',
  },
  actions: {
    can(permission: string): boolean {
      return this.permissions.includes('*') || this.permissions.includes(permission)
    },
    persist() {
      setToken(this.token)
      if (this.user) localStorage.setItem(USER_KEY, JSON.stringify(this.user))
    },
    async login(username: string, password: string) {
      this.loading = true
      try {
        const response = await authApi.login(username, password)
        this.token = response.token
        this.user = response.user
        this.permissions = response.permissions
        this.roleLabel = response.role_label
        this.initialized = true
        this.persist()
        return response
      } finally {
        this.loading = false
      }
    },
    async fetchMe() {
      if (!this.token) {
        this.initialized = true
        return null
      }
      try {
        const response = await authApi.me()
        this.user = response.user
        this.permissions = response.permissions
        this.roleLabel = response.role_label
        this.persist()
        return response.user
      } catch {
        this.clear()
        return null
      } finally {
        this.initialized = true
      }
    },
    async logout() {
      try {
        if (this.token) await authApi.logout()
      } catch {
        // local session must still be cleared when the network is unavailable
      }
      this.clear()
    },
    clear() {
      this.token = ''
      this.user = null
      this.permissions = []
      this.roleLabel = ''
      setToken('')
      localStorage.removeItem(USER_KEY)
    },
  },
})
