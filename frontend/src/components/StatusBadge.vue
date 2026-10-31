<script setup lang="ts">
import { computed } from 'vue'
import { statusTone } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    status?: string | null
    label?: string | null
    tone?: string
    dot?: boolean
  }>(),
  { dot: true },
)

const resolvedTone = computed(() => props.tone || statusTone(props.status))
const resolvedLabel = computed(() => props.label || props.status || '—')
</script>

<template>
  <span class="badge" :class="`badge-${resolvedTone}`">
    <span v-if="dot" class="dot" />
    {{ resolvedLabel }}
  </span>
</template>
