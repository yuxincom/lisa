export function cssVar(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

export interface ChartTheme {
  text: string
  text2: string
  text3: string
  border: string
  panel: string
  accent: string
  teal: string
  blue: string
  success: string
  warning: string
  danger: string
  violet: string
  font: string
}

export function chartTheme(): ChartTheme {
  return {
    text: cssVar('--text', '#e9f0fb'),
    text2: cssVar('--text-2', '#a8b9d1'),
    text3: cssVar('--text-3', '#7186a3'),
    border: cssVar('--border', 'rgba(122,158,204,.14)'),
    panel: cssVar('--panel-solid', '#0f1a2c'),
    accent: cssVar('--accent', '#f0a43a'),
    teal: cssVar('--teal', '#4fd1c5'),
    blue: cssVar('--blue', '#5b9dff'),
    success: cssVar('--success', '#3ddc97'),
    warning: cssVar('--warning', '#f6c445'),
    danger: cssVar('--danger', '#ff6373'),
    violet: cssVar('--violet', '#9b8cff'),
    font: cssVar('--font', 'Inter, sans-serif'),
  }
}

export function withAlpha(hex: string, alpha: number): string {
  const value = hex.trim()
  if (!value.startsWith('#') || (value.length !== 7 && value.length !== 4)) return value
  const full = value.length === 4 ? `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}` : value
  const r = parseInt(full.slice(1, 3), 16)
  const g = parseInt(full.slice(3, 5), 16)
  const b = parseInt(full.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
