<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = withDefaults(
  defineProps<{
    level?: string | null
    showLabel?: boolean
  }>(),
  { showLabel: false },
)

const TONE: Record<string, string> = {
  公开: 'muted',
  内部: 'blue',
  秘密: 'warning',
  机密: 'danger',
}

const resolved = computed(() => props.level || '内部')
const tone = computed(() => TONE[resolved.value] || 'violet')
const sensitive = computed(() => resolved.value === '秘密' || resolved.value === '机密')
</script>

<template>
  <span class="badge" :class="`badge-${tone}`">
    <AppIcon v-if="sensitive" name="lock" :size="11" />
    {{ showLabel ? `密级 ${resolved}` : resolved }}
  </span>
</template>
