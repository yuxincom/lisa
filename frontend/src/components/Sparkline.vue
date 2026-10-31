<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    color?: string
    fill?: boolean
    height?: number
  }>(),
  { color: 'var(--accent)', fill: true, height: 34 },
)

const id = `spark-${Math.random().toString(36).slice(2, 9)}`

const geometry = computed(() => {
  const values = (props.values || []).filter((value) => Number.isFinite(value))
  if (values.length < 2) return { line: '', area: '' }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const width = 100
  const height = 30
  const step = width / (values.length - 1)
  const points = values.map((value, index) => {
    const x = index * step
    const y = height - ((value - min) / span) * (height - 3) - 1.5
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })
  return {
    line: `M${points.join(' L')}`,
    area: `M0,${height} L${points.join(' L')} L${width},${height} Z`,
  }
})
</script>

<template>
  <svg :viewBox="`0 0 100 30`" :style="{ height: `${height}px`, width: '100%' }" preserveAspectRatio="none">
    <defs>
      <linearGradient :id="id" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.32" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path v-if="fill && geometry.area" :d="geometry.area" :fill="`url(#${id})`" />
    <path
      v-if="geometry.line"
      :d="geometry.line"
      fill="none"
      :stroke="color"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      vector-effect="non-scaling-stroke"
    />
  </svg>
</template>
