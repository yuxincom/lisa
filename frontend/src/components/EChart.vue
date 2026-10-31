<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useUiStore } from '@/stores/ui'

echarts.use([
  BarChart,
  LineChart,
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    option: Record<string, unknown>
    height?: string
    loading?: boolean
  }>(),
  { height: '260px', loading: false },
)

const ui = useUiStore()
const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<ReturnType<typeof echarts.init> | null>(null)
let observer: ResizeObserver | null = null

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function baseOption() {
  return {
    backgroundColor: 'transparent',
    textStyle: {
      color: css('--text-2'),
      fontFamily: css('--font') || 'Inter, sans-serif',
      fontSize: 11,
    },
    animationDuration: 650,
    animationEasing: 'cubicOut',
    grid: { left: 8, right: 14, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      backgroundColor: css('--panel-solid'),
      borderColor: css('--border-strong'),
      borderWidth: 1,
      textStyle: { color: css('--text'), fontSize: 12 },
      padding: [8, 11],
      extraCssText: 'box-shadow: 0 12px 32px rgba(0,0,0,.28); border-radius: 9px;',
    },
  }
}

function mergeOption(): EChartsCoreOption {
  const base = baseOption()
  return {
    ...base,
    ...props.option,
    textStyle: { ...base.textStyle, ...((props.option.textStyle as object) || {}) },
    tooltip: { ...base.tooltip, ...((props.option.tooltip as object) || {}) },
    grid: { ...base.grid, ...((props.option.grid as object) || {}) },
  } as EChartsCoreOption
}

function init() {
  if (!container.value) return
  chart.value = echarts.init(container.value, undefined, { renderer: 'canvas' })
  chart.value.setOption(mergeOption(), true)
}

function refresh() {
  if (!container.value) return
  if (chart.value) chart.value.dispose()
  init()
}

onMounted(() => {
  init()
  observer = new ResizeObserver(() => chart.value?.resize())
  if (container.value) observer.observe(container.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.dispose()
})

watch(
  () => props.option,
  () => chart.value?.setOption(mergeOption(), true),
  { deep: true },
)

watch(() => ui.theme, refresh)

watch(
  () => props.loading,
  (loading) => {
    if (!chart.value) return
    if (loading) {
      chart.value.showLoading('default', {
        text: '加载中',
        color: css('--accent'),
        maskColor: 'transparent',
        textColor: css('--text-3'),
      })
    } else {
      chart.value.hideLoading()
    }
  },
)
</script>

<template>
  <div ref="container" class="echart" :style="{ height }" />
</template>

<style scoped>
.echart {
  width: 100%;
  min-width: 0;
}
</style>
