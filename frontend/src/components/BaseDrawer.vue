<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    subtitle?: string
    width?: string
  }>(),
  { width: '600px' },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

function close() {
  emit('update:modelValue', false)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.modelValue) close()
}

watch(
  () => props.modelValue,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="modelValue" class="drawer-root" role="dialog" aria-modal="true">
        <div class="drawer-overlay" @click="close" />
        <aside class="drawer-card" :style="{ maxWidth: width }">
          <header class="drawer-head">
            <slot name="header">
              <div class="drawer-heading">
                <h3 class="drawer-title">{{ title }}</h3>
                <p v-if="subtitle" class="drawer-sub">{{ subtitle }}</p>
              </div>
            </slot>
            <button class="drawer-close" type="button" aria-label="关闭" @click="close">
              <AppIcon name="close" :size="17" />
            </button>
          </header>
          <div class="drawer-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="drawer-foot">
            <slot name="footer" />
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-root {
  position: fixed;
  inset: 0;
  z-index: 1100;
}

.drawer-overlay {
  position: absolute;
  inset: 0;
  background: rgba(3, 8, 16, 0.62);
  backdrop-filter: blur(4px);
}

.drawer-card {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel-solid);
  border-left: 1px solid var(--border-strong);
  box-shadow: -24px 0 80px rgba(0, 0, 0, 0.42);
  overflow: hidden;
}

.drawer-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 2px;
  background: linear-gradient(180deg, var(--accent), var(--teal), transparent 75%);
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 19px 22px 15px;
  border-bottom: 1px solid var(--border);
}

.drawer-heading {
  min-width: 0;
}

.drawer-title {
  font-size: 16px;
  font-weight: 680;
  letter-spacing: -0.01em;
}

.drawer-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
  word-break: break-all;
}

.drawer-close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-3);
  flex: none;
  transition: all 0.16s ease;
}

.drawer-close:hover {
  color: var(--text);
  border-color: var(--border-strong);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px;
}

.drawer-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 13px 22px;
  border-top: 1px solid var(--border);
  background: var(--panel-inset);
  flex-wrap: wrap;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.24s ease;
}

.drawer-enter-active .drawer-card,
.drawer-leave-active .drawer-card {
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer-card,
.drawer-leave-to .drawer-card {
  transform: translateX(100%);
}

@media (max-width: 640px) {
  .drawer-card {
    max-width: none !important;
  }
  .drawer-head {
    padding: 16px;
  }
  .drawer-body {
    padding: 16px;
  }
  .drawer-foot {
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  }
  .drawer-foot :deep(.btn) {
    flex: 1;
  }
}
</style>
