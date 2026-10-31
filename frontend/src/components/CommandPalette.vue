<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { systemApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { ALL_NAV_ITEMS } from '@/router/nav'
import AppIcon from './AppIcon.vue'

interface PaletteItem {
  key: string
  title: string
  subtitle: string
  route: string
  icon: string
  meta?: string
}

const ui = useUiStore()
const auth = useAuthStore()
const router = useRouter()
const input = ref<HTMLInputElement | null>(null)
const query = ref('')
const loading = ref(false)
const results = ref<PaletteItem[]>([])
const activeIndex = ref(0)
let debounce: number | undefined
let requestSeq = 0

const shortcuts = computed<PaletteItem[]>(() =>
  ALL_NAV_ITEMS.filter((item) => auth.can(item.permission)).map((item) => ({
    key: `nav-${item.path}`,
    title: item.title,
    subtitle: item.description,
    route: item.path,
    icon: item.icon,
    meta: '快捷导航',
  })),
)

const displayItems = computed(() => (query.value.trim() ? results.value : shortcuts.value))

watch(
  () => ui.commandOpen,
  async (open) => {
    if (open) {
      query.value = ''
      results.value = []
      activeIndex.value = 0
      await nextTick()
      input.value?.focus()
    }
  },
)

watch(query, (value) => {
  activeIndex.value = 0
  if (debounce) window.clearTimeout(debounce)
  const text = value.trim()
  if (!text) {
    results.value = []
    loading.value = false
    return
  }
  loading.value = true
  debounce = window.setTimeout(async () => {
    const seq = ++requestSeq
    try {
      const response = await systemApi.search(text)
      if (seq !== requestSeq) return
      const items: PaletteItem[] = []
      for (const order of response.orders || []) {
        items.push({
          key: `order-${order.id}`,
          title: order.title,
          subtitle: order.subtitle,
          route: `/orders?focus=${order.id}`,
          icon: 'orders',
          meta: `订单 · ${order.priority} · ${order.status}`,
        })
      }
      for (const plan of response.plans || []) {
        items.push({
          key: `plan-${plan.id}`,
          title: plan.title,
          subtitle: plan.subtitle,
          route: `/plans?plan=${plan.id}`,
          icon: 'approval',
          meta: `方案 · ${plan.status}`,
        })
      }
      for (const change of response.changes || []) {
        items.push({
          key: `change-${change.id}`,
          title: change.title,
          subtitle: change.subtitle,
          route: `/changes?change=${change.id}`,
          icon: 'change',
          meta: `扰动 · ${change.status}`,
        })
      }
      results.value = items.slice(0, 18)
    } catch {
      if (seq === requestSeq) results.value = []
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }, 240)
})

function close() {
  ui.commandOpen = false
}

function go(item: PaletteItem | undefined) {
  if (!item) return
  close()
  void router.push(item.route)
}

function onKeydown(event: KeyboardEvent) {
  if (!ui.commandOpen) return
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = Math.min(displayItems.value.length - 1, activeIndex.value + 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value = Math.max(0, activeIndex.value - 1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    go(displayItems.value[activeIndex.value])
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="palette">
      <div v-if="ui.commandOpen" class="palette-root" @keydown="onKeydown">
        <div class="palette-overlay" @click="close" />
        <div class="palette-card" role="dialog" aria-label="全局搜索">
          <div class="palette-input-wrap">
            <AppIcon name="search" :size="18" />
            <input
              ref="input"
              v-model="query"
              class="palette-input"
              type="text"
              placeholder="搜索订单号、方案、扰动事件，或输入页面名称…"
              autocomplete="off"
            />
            <span v-if="loading" class="spinner" />
            <kbd>ESC</kbd>
          </div>

          <div class="palette-results">
            <div class="palette-group-title">
              {{ query.trim() ? '检索结果' : '快捷导航' }}
              <span class="muted">{{ displayItems.length }}</span>
            </div>
            <button
              v-for="(item, index) in displayItems"
              :key="item.key"
              class="palette-item"
              :class="{ active: index === activeIndex }"
              type="button"
              @mouseenter="activeIndex = index"
              @click="go(item)"
            >
              <span class="palette-icon"><AppIcon :name="item.icon" :size="16" /></span>
              <span class="palette-copy">
                <span class="palette-title">{{ item.title }}</span>
                <span class="palette-sub">{{ item.subtitle }}</span>
              </span>
              <span v-if="item.meta" class="palette-meta">{{ item.meta }}</span>
              <AppIcon name="chevronRight" :size="13" class="palette-arrow" />
            </button>
            <div v-if="query.trim() && !loading && !displayItems.length" class="palette-empty">
              <AppIcon name="search" :size="20" />
              <span>没有找到与「{{ query }}」匹配的内容</span>
            </div>
            <div v-if="!query.trim()" class="palette-hint">
              <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
              <span><kbd>↵</kbd> 打开</span>
              <span><kbd>ESC</kbd> 关闭</span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.palette-root {
  position: fixed;
  inset: 0;
  z-index: 1500;
  display: flex;
  justify-content: center;
  padding: min(13vh, 110px) 16px 16px;
}

.palette-overlay {
  position: absolute;
  inset: 0;
  background: rgba(3, 8, 16, 0.68);
  backdrop-filter: blur(6px);
}

.palette-card {
  position: relative;
  width: min(650px, 100%);
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  border: 1px solid var(--border-strong);
  background: var(--panel-solid);
  box-shadow: 0 36px 100px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.palette-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), var(--teal), transparent);
}

.palette-input-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 15px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
}

.palette-input {
  flex: 1;
  border: 0;
  background: transparent;
  font-size: 14px;
  color: var(--text);
  outline: none;
  min-width: 0;
}

.palette-input::placeholder {
  color: var(--text-3);
}

.palette-input-wrap kbd {
  font-family: var(--mono);
  font-size: 9px;
  padding: 3px 5px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--panel-strong);
  color: var(--text-3);
}

.palette-results {
  padding: 8px;
  overflow-y: auto;
}

.palette-group-title {
  display: flex;
  justify-content: space-between;
  padding: 8px 10px 6px;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--text-3);
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  text-align: left;
  transition: background-color 0.13s ease;
}

.palette-item.active {
  background: var(--accent-soft);
}

.palette-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--panel-inset);
  color: var(--accent);
  flex: none;
}

.palette-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.palette-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.palette-sub {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.palette-meta {
  font-size: 9.5px;
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 99px;
  padding: 2px 7px;
  white-space: nowrap;
  flex: none;
}

.palette-arrow {
  color: var(--text-3);
  opacity: 0.5;
  flex: none;
}

.palette-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}

.palette-hint {
  display: flex;
  gap: 16px;
  padding: 10px 12px 6px;
  border-top: 1px solid var(--border);
  margin-top: 6px;
  font-size: 10px;
  color: var(--text-3);
}

.palette-hint kbd {
  font-family: var(--mono);
  font-size: 9px;
  padding: 2px 4px;
  margin-right: 3px;
  border-radius: 3px;
  border: 1px solid var(--border);
  background: var(--panel-strong);
}

.palette-enter-active,
.palette-leave-active {
  transition: opacity 0.18s ease;
}

.palette-enter-active .palette-card,
.palette-leave-active .palette-card {
  transition: transform 0.22s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.18s ease;
}

.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}

.palette-enter-from .palette-card,
.palette-leave-to .palette-card {
  opacity: 0;
  transform: translateY(-8px) scale(0.985);
}

@media (max-width: 640px) {
  .palette-root {
    padding: 12px;
    align-items: flex-start;
    padding-top: 74px;
  }
  .palette-card {
    max-height: 76vh;
  }
}
</style>
