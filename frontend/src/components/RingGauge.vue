<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    size?: number
    stroke?: number
    color?: string
    label?: string
    sublabel?: string
    suffix?: string
  }>(),
  { size: 128, stroke: 9, color: 'var(--accent)', suffix: '%' },
)

const radius = computed(() => (props.size - props.stroke) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const offset = computed(() => {
  const clamped = Math.min(100, Math.max(0, props.value))
  return circumference.value * (1 - clamped / 100)
})
</script>

<template>
  <div class="ring" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`">
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        stroke="var(--border)"
        :stroke-width="stroke"
      />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"
        class="ring-progress"
      />
    </svg>
    <div class="ring-content">
      <div class="ring-value num">
        {{ value.toFixed(value % 1 === 0 ? 0 : 1) }}<span>{{ suffix }}</span>
      </div>
      <div v-if="label" class="ring-label">{{ label }}</div>
      <div v-if="sublabel" class="ring-sub">{{ sublabel }}</div>
    </div>
  </div>
</template>

<style scoped>
.ring {
  position: relative;
  display: grid;
  place-items: center;
  flex: none;
}

.ring svg {
  position: absolute;
  inset: 0;
}

.ring-progress {
  transition: stroke-dashoffset 0.9s cubic-bezier(0.22, 1, 0.36, 1);
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 30%, transparent));
}

.ring-content {
  position: relative;
  text-align: center;
  z-index: 1;
}

.ring-value {
  font-size: 24px;
  font-weight: 720;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.ring-value span {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  margin-left: 1px;
}

.ring-label {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
}

.ring-sub {
  font-size: 10px;
  color: var(--text-3);
  opacity: 0.75;
  margin-top: 1px;
}
</style>
