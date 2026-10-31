<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import AppIcon from './AppIcon.vue'

const ui = useUiStore()

const iconMap: Record<string, string> = {
  success: 'check',
  error: 'warning',
  warning: 'info',
  info: 'info',
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="toast in ui.toasts" :key="toast.id" class="toast" :class="`toast-${toast.tone}`">
          <span class="toast-icon">
            <AppIcon :name="iconMap[toast.tone]" :size="15" />
          </span>
          <div class="toast-copy">
            <div class="toast-title">{{ toast.title }}</div>
            <div v-if="toast.message" class="toast-message">{{ toast.message }}</div>
          </div>
          <button class="toast-close" aria-label="关闭提示" @click="ui.dismissToast(toast.id)">
            <AppIcon name="close" :size="13" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 1400;
  display: flex;
  flex-direction: column;
  gap: 9px;
  width: min(370px, calc(100vw - 28px));
  pointer-events: none;
}

.toast {
  --tone: var(--blue);
  --tone-soft: var(--blue-soft);
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 12px 12px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--tone) 28%, var(--border));
  background: var(--panel-solid);
  box-shadow: 0 16px 44px rgba(0, 0, 0, 0.35);
  pointer-events: auto;
  position: relative;
  overflow: hidden;
}

.toast::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 2px;
  background: var(--tone);
}

.toast-success {
  --tone: var(--success);
  --tone-soft: var(--success-soft);
}
.toast-error {
  --tone: var(--danger);
  --tone-soft: var(--danger-soft);
}
.toast-warning {
  --tone: var(--warning);
  --tone-soft: var(--warning-soft);
}

.toast-icon {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: var(--tone);
  background: var(--tone-soft);
  flex: none;
}

.toast-copy {
  flex: 1;
  min-width: 0;
}

.toast-title {
  font-size: 13px;
  font-weight: 620;
  color: var(--text);
  line-height: 1.4;
}

.toast-message {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.5;
  word-break: break-word;
}

.toast-close {
  border: 0;
  background: transparent;
  color: var(--text-3);
  padding: 2px;
  border-radius: 5px;
  flex: none;
}

.toast-close:hover {
  color: var(--text);
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(24px) scale(0.97);
}

@media (max-width: 640px) {
  .toast-stack {
    top: auto;
    bottom: calc(74px + env(safe-area-inset-bottom));
    left: 14px;
    right: 14px;
    width: auto;
  }
}
</style>
