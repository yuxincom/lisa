<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import AppIcon from './AppIcon.vue'

const ui = useUiStore()
</script>

<template>
  <button class="theme-toggle" type="button" :aria-label="ui.isDark ? '切换为浅色主题' : '切换为深色主题'" @click="ui.toggleTheme">
    <span class="track">
      <span class="thumb" :class="{ light: !ui.isDark }">
        <AppIcon :name="ui.isDark ? 'moon' : 'sun'" :size="13" />
      </span>
    </span>
  </button>
</template>

<style scoped>
.theme-toggle {
  border: 0;
  background: transparent;
  padding: 0;
  display: inline-flex;
  align-items: center;
}

.track {
  display: inline-flex;
  align-items: center;
  width: 44px;
  height: 24px;
  padding: 2px;
  border-radius: 99px;
  border: 1px solid var(--border-strong);
  background: var(--panel-inset);
  transition: background-color 0.2s ease;
}

.thumb {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: linear-gradient(145deg, #2a3f5d, #16263d);
  color: #cfe0f5;
  transform: translateX(0);
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease, color 0.2s ease;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}

.thumb.light {
  transform: translateX(20px);
  background: linear-gradient(145deg, #ffe6ac, #f0a43a);
  color: #5b3a05;
}

.theme-toggle:hover .track {
  border-color: var(--border-accent);
}
</style>
