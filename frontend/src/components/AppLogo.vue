<script setup lang="ts">
defineProps<{ collapsed?: boolean }>()
</script>

<template>
  <div class="logo" :class="{ collapsed }">
    <span class="logo-mark">
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <defs>
          <linearGradient id="lisa-logo" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#f4b257" />
            <stop offset="1" stop-color="#4fd1c5" />
          </linearGradient>
        </defs>
        <path d="M22 3 39 13v18L22 41 5 31V13Z" fill="none" stroke="url(#lisa-logo)" stroke-width="1.6" opacity=".9" />
        <path d="M22 11 32 17v11l-10 6-10-6V17Z" fill="url(#lisa-logo)" opacity=".16" />
        <path d="M22 14.5 28.5 18v8L22 30l-6.5-4v-8Z" fill="url(#lisa-logo)" opacity=".92" />
        <circle cx="22" cy="22" r="2.4" fill="#0a1322" />
        <circle cx="22" cy="3" r="1.5" fill="#f4b257" />
        <circle cx="39" cy="31" r="1.5" fill="#4fd1c5" />
      </svg>
    </span>
    <span v-if="!collapsed" class="logo-text">
      <span class="logo-title">LISA</span>
      <span class="logo-sub">黎阳智能排产智能体</span>
    </span>
  </div>
</template>

<style scoped>
.logo {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.logo-mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: linear-gradient(155deg, rgba(240, 164, 58, 0.1), rgba(79, 209, 197, 0.05));
  border: 1px solid var(--border);
  box-shadow: inset 0 0 18px rgba(240, 164, 58, 0.05);
  flex: none;
}

.logo-mark svg {
  width: 32px;
  height: 32px;
}

.logo-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.15;
}

.logo-title {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.14em;
  background: linear-gradient(90deg, #f7c06a, #f0a43a 45%, #7fe0d5);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.logo-sub {
  margin-top: 2px;
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.logo.collapsed {
  justify-content: center;
}
</style>
