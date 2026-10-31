<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import Sparkline from './Sparkline.vue'
import type { Kpi } from '@/types'

const props = defineProps<{ kpi: Kpi }>()

const iconMap: Record<string, string> = {
  adoption: 'target',
  full_reschedule: 'clock',
  change_eval: 'zap',
  local_reschedule: 'activity',
  kit_rate: 'kits',
  trial_rate: 'factory',
  accuracy: 'spark',
  bottleneck: 'cpu',
}

const tone = computed(() => {
  if (props.kpi.status === 'good') return 'success'
  if (props.kpi.status === 'warning') return 'warning'
  return 'danger'
})

const toneColor = computed(() => {
  if (props.kpi.status === 'good') return 'var(--success)'
  if (props.kpi.status === 'warning') return 'var(--warning)'
  return 'var(--danger)'
})

const displayValue = computed(() => {
  const value = props.kpi.value
  if (value >= 1000) return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
})
</script>

<template>
  <article class="stat-card" :class="`tone-${tone}`">
    <div class="stat-top">
      <span class="stat-icon">
        <AppIcon :name="iconMap[kpi.key] || 'activity'" :size="17" />
      </span>
      <span class="badge" :class="`badge-${tone}`">
        <span class="dot" />
        {{ kpi.status === 'good' ? '达标' : kpi.status === 'warning' ? '关注' : '偏离' }}
      </span>
    </div>
    <div class="stat-label">{{ kpi.label }}</div>
    <div class="stat-value">
      <span class="num">{{ displayValue }}</span>
      <span class="stat-unit">{{ kpi.unit }}</span>
    </div>
    <div class="stat-foot">
      <span class="stat-target">目标 {{ kpi.target_label }}</span>
      <span class="stat-note">{{ kpi.note }}</span>
    </div>
    <div class="stat-spark">
      <Sparkline :values="kpi.spark" :color="toneColor" :height="30" />
    </div>
  </article>
</template>

<style scoped>
.stat-card {
  position: relative;
  padding: 15px 16px 13px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
  min-height: 140px;
}

.stat-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--tone);
  opacity: 0.75;
}

.stat-card::after {
  content: '';
  position: absolute;
  width: 130px;
  height: 130px;
  right: -48px;
  top: -58px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--tone-soft), transparent 68%);
  pointer-events: none;
}

.stat-card.tone-success {
  --tone: var(--success);
  --tone-soft: var(--success-soft);
}
.stat-card.tone-warning {
  --tone: var(--warning);
  --tone-soft: var(--warning-soft);
}
.stat-card.tone-danger {
  --tone: var(--danger);
  --tone-soft: var(--danger-soft);
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: var(--shadow);
}

.stat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.stat-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  color: var(--tone);
  background: var(--tone-soft);
  border: 1px solid color-mix(in srgb, var(--tone) 22%, transparent);
}

.stat-label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 560;
  letter-spacing: 0.01em;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  margin: 3px 0 2px;
}

.stat-value .num {
  font-size: clamp(26px, 2.4vw, 32px);
  font-weight: 720;
  line-height: 1.15;
  letter-spacing: -0.02em;
  color: var(--text);
}

.stat-unit {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 600;
}

.stat-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10.5px;
  color: var(--text-3);
  min-height: 16px;
}

.stat-target {
  color: color-mix(in srgb, var(--tone) 88%, var(--text));
  font-weight: 600;
}

.stat-note {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-spark {
  margin-top: 7px;
  opacity: 0.85;
}
</style>
