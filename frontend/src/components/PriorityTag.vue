<script setup lang="ts">
defineProps<{ priority: string }>()
</script>

<template>
  <span class="priority" :class="`priority-${priority}`">{{ priority }}</span>
</template>
