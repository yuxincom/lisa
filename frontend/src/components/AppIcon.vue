<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
    strokeWidth?: number
  }>(),
  { size: 18, strokeWidth: 1.8 },
)

const icons: Record<string, string> = {
  dashboard:
    '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  gantt:
    '<path d="M4 5h9"/><path d="M4 12h15"/><path d="M4 19h6"/><path d="M2.5 3v18"/><rect x="6.5" y="3" width="7" height="4" rx="1"/><rect x="10.5" y="10" width="9" height="4" rx="1"/><rect x="8.5" y="17" width="4" height="4" rx="1"/>',
  approval:
    '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1.5"/><path d="m9 14 2 2 4-4"/>',
  change:
    '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M6 8.5v7"/><path d="M8.5 6h4a3 3 0 0 1 3 3v0M18 11.5c0 4-4 4.5-7 4.5H8.5"/>',
  kits:
    '<path d="m7.5 4.3 9 5.2"/><path d="M21 8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="M3.3 7 12 12l8.7-5"/><path d="M12 22V12"/>',
  agents:
    '<rect x="9" y="2.5" width="6" height="5" rx="1.5"/><rect x="2.5" y="16.5" width="6" height="5" rx="1.5"/><rect x="15.5" y="16.5" width="6" height="5" rx="1.5"/><path d="M12 7.5v4M5.5 16.5v-2a3 3 0 0 1 3-3h7a3 3 0 0 1 3 3v2"/><path d="M12 11.5v3"/>',
  data:
    '<ellipse cx="12" cy="5.5" rx="7.5" ry="3.5"/><path d="M4.5 5.5v6c0 1.9 3.4 3.5 7.5 3.5s7.5-1.6 7.5-3.5v-6"/><path d="M4.5 11.5v6c0 1.9 3.4 3.5 7.5 3.5s7.5-1.6 7.5-3.5v-6"/>',
  knowledge:
    '<path d="M12 6.5S9.5 4 4.5 4c-1 0-1.5.4-1.5 1.4v12.2c0 .9.5 1.4 1.5 1.4 5 0 7.5 2 7.5 2s2.5-2 7.5-2c1 0 1.5-.5 1.5-1.4V5.4c0-1-.5-1.4-1.5-1.4-5 0-7.5 2.5-7.5 2.5Z"/><path d="M12 6.5V21"/>',
  audit:
    '<path d="M12 22s8-3.5 8-9.5V5.5L12 2.5 4 5.5V12.5C4 18.5 12 22 12 22Z"/><path d="m8.5 11.5 2.3 2.3 4.7-5"/>',
  alerts:
    '<path d="M18 8.5a6 6 0 1 0-12 0c0 6-2.5 7-2.5 7h17S18 14.5 18 8.5"/><path d="M10.3 20a2 2 0 0 0 3.4 0"/>',
  settings:
    '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h7M15 18h5"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="13" cy="18" r="2"/>',
  orders:
    '<path d="M14 2.5H6a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8.5Z"/><path d="M14 2.5v6h6"/><path d="M8.5 13h7M8.5 17h4.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/>',
  sun:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  moon: '<path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/>',
  menu: '<path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevronRight: '<path d="m9 6 6 6-6 6"/>',
  'chevron-right': '<path d="m9 6 6 6-6 6"/>',
  'arrow-right': '<path d="M4 12h15M13 6l6 6-6 6"/>',
  alert: '<path d="M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17v.1"/>',
  chevronLeft: '<path d="m15 6-6 6 6 6"/>',
  check: '<path d="m4.5 12.5 5 5 10-11"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  refresh:
    '<path d="M20 5v5h-5"/><path d="M20 10a8 8 0 1 0-.7 5.5"/>',
  play: '<path d="m8 4.5 11 7.5-11 7.5Z"/>',
  download:
    '<path d="M12 3v11M7.5 9.5 12 14l4.5-4.5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  signature:
    '<path d="M3 20c3 0 4-1.5 5.5-5S11 5 13.5 5s1.5 5 0 8 1.5 3 3 1 2.5-.5 4-1"/><path d="M4 21h16"/>',
  shield:
    '<path d="M12 22s8-3.5 8-9.5V5.5L12 2.5 4 5.5V12.5C4 18.5 12 22 12 22Z"/><path d="M12 8v4M12 15.5v.1"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  filter: '<path d="M3 5h18l-7 8v5.5l-4 2V13Z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>',
  lock: '<rect x="4" y="10.5" width="16" height="11" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
  arrowRight: '<path d="M4 12h16M14 6l6 6-6 6"/>',
  arrowUp: '<path d="M12 20V4M6 10l6-6 6 6"/>',
  arrowDown: '<path d="M12 4v16M6 14l6 6 6-6"/>',
  zap: '<path d="M13 2.5 4.5 13.5H11L10 21.5 19.5 10H13Z"/>',
  warning: '<path d="M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17v.1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.1"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.2 1.2"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.2-1.2"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2.5v3M15 2.5v3M9 18.5v3M15 18.5v3M2.5 9h3M2.5 15h3M18.5 9h3M18.5 15h3"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>',
  layers:
    '<path d="m12 2.5 9 5-9 5-9-5Z"/><path d="m3 12 9 5 9-5M3 16.5l9 5 9-5"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  external: '<path d="M14 3h7v7M21 3l-9 9"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  calendar:
    '<rect x="3" y="4.5" width="18" height="17" rx="2"/><path d="M8 2.5v4M16 2.5v4M3 9.5h18"/><path d="M8 14h2M14 14h2M8 17.5h2M14 17.5h2"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  send: '<path d="M21.5 2.5 10.5 13.5M21.5 2.5 14.5 21.5l-4-8-8-4Z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  target:
    '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
  factory:
    '<path d="M3 20.5V9l6 3.5V9l6 3.5V6l6 3v11.5Z"/><path d="M3 20.5h18M7 16.5h2M12 16.5h2M17 16.5h1"/>',
  route:
    '<circle cx="6" cy="5" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.5 5H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.5"/>',
  stamp:
    '<path d="M5 21h14M6 18h12v-1a3 3 0 0 0-3-3H9a3 3 0 0 0-3 3Z"/><path d="M12 14V9M9.5 5.5A2.5 2.5 0 0 1 14.5 5.5c0 1.5-2.5 1.8-2.5 3.5"/>',
  terminal: '<path d="m4 7 5 5-5 5M12 17h8"/>',
  spark: '<path d="M12 2.5 14.4 9l6.6 2.5-6.6 2.5L12 21l-2.4-7L3 11.5 9.6 9Z"/>',
  chevrons: '<path d="m6 6 6 6-6 6M13 6l6 6-6 6"/>',
  key: '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 8-8M17 6l2.5 2.5M14.5 9l2 2"/>',
  database: '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/><path d="M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.1M3.5 12h.1M3.5 18h.1"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  reset: '<path d="M3 12a9 9 0 1 0 3-6.7M3 4.5V10h5.5"/>',
}

const inner = computed(() => icons[props.name] || icons.info)
const dimension = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
</script>

<template>
  <svg
    :width="dimension"
    :height="dimension"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="inner"
  />
</template>
