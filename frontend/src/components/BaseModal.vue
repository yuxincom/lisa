<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    subtitle?: string
    width?: string
    closable?: boolean
  }>(),
  { width: '520px', closable: true },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

function close() {
  if (props.closable) emit('update:modelValue', false)
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
    <Transition name="modal">
      <div v-if="modelValue" class="modal-root" role="dialog" aria-modal="true">
        <div class="modal-overlay" @click="close" />
        <div class="modal-card" :style="{ maxWidth: width }">
          <header v-if="title || $slots.header" class="modal-head">
            <slot name="header">
              <div>
                <h3 class="modal-title">{{ title }}</h3>
                <p v-if="subtitle" class="modal-sub">{{ subtitle }}</p>
              </div>
            </slot>
            <button v-if="closable" class="modal-close" type="button" aria-label="关闭" @click="close">
              <AppIcon name="close" :size="17" />
            </button>
          </header>
          <div class="modal-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="modal-foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-root {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  padding: 20px;
}

.modal-overlay {
  position: absolute;
  inset: 0;
  background: rgba(3, 8, 16, 0.72);
  backdrop-filter: blur(6px);
}

:root[data-theme='light'] .modal-overlay {
  background: rgba(24, 38, 60, 0.4);
}

.modal-card {
  position: relative;
  width: 100%;
  max-height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
  background: var(--panel-solid);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: 0 32px 90px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.modal-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), var(--teal), transparent);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px 16px;
  border-bottom: 1px solid var(--border);
}

.modal-title {
  font-size: 16.5px;
  font-weight: 680;
  letter-spacing: -0.01em;
}

.modal-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
}

.modal-close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-3);
  transition: all 0.16s ease;
  flex: none;
}

.modal-close:hover {
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--panel-strong);
}

.modal-body {
  padding: 20px 22px;
  overflow: auto;
  flex: 1;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 22px;
  border-top: 1px solid var(--border);
  background: var(--panel-inset);
  flex-wrap: wrap;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.22s ease;
}

.modal-enter-active .modal-card,
.modal-leave-active .modal-card {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-card,
.modal-leave-to .modal-card {
  transform: translateY(14px) scale(0.98);
  opacity: 0;
}

@media (max-width: 640px) {
  .modal-root {
    padding: 0;
    align-items: end;
  }
  .modal-card {
    max-height: 92vh;
    border-radius: 18px 18px 0 0;
    max-width: none;
  }
  .modal-head {
    padding: 18px 16px 14px;
  }
  .modal-body {
    padding: 16px;
  }
  .modal-foot {
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  }
  .modal-foot :deep(.btn) {
    flex: 1;
  }
}
</style>
