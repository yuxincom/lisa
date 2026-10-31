<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
  eyebrow?: string
}>()
</script>

<template>
  <header class="page-header">
    <div class="page-heading">
      <div v-if="eyebrow" class="page-eyebrow">
        <span class="eyebrow-line" />
        {{ eyebrow }}
      </div>
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions">
      <slot name="actions" />
    </div>
    <div v-if="$slots.meta" class="page-meta">
      <slot name="meta" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.page-heading {
  min-width: 0;
}

.page-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 7px;
}

.eyebrow-line {
  width: 22px;
  height: 1px;
  background: linear-gradient(90deg, var(--accent), transparent);
}

.page-title {
  font-family: var(--font-display);
  font-size: clamp(21px, 2.1vw, 28px);
  line-height: 1.2;
  font-weight: 720;
  letter-spacing: -0.01em;
}

.page-subtitle {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-3);
  max-width: 760px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.page-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-3);
}

@media (max-width: 767px) {
  .page-header {
    align-items: flex-start;
    margin-bottom: 14px;
  }
  .page-actions {
    width: 100%;
  }
  .page-actions :deep(.btn) {
    flex: 1;
  }
}
</style>
