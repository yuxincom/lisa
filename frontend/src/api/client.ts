const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || '/api'
const TOKEN_KEY = 'lisa_token'

export class ApiError extends Error {
  status: number
  code: string
  detail: unknown

  constructor(status: number, message: string, code = 'REQUEST_FAILED', detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function resolveMessage(payload: unknown, fallback: string): { message: string; code: string } {
  if (payload && typeof payload === 'object') {
    const detail = (payload as Record<string, unknown>).detail
    if (typeof detail === 'string') return { message: detail, code: 'REQUEST_FAILED' }
    if (detail && typeof detail === 'object') {
      const record = detail as Record<string, unknown>
      const message = typeof record.message === 'string' ? record.message : fallback
      const code = typeof record.code === 'string' ? record.code : 'REQUEST_FAILED'
      return { message, code }
    }
  }
  return { message: fallback, code: 'REQUEST_FAILED' }
}

async function request<T>(method: string, path: string, body?: unknown, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Accept', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (body !== undefined && !(body instanceof FormData)) headers.set('Content-Type', 'application/json')

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      ...options,
    })
  } catch {
    throw new ApiError(0, '无法连接 LISA 服务端，请检查内网服务状态', 'NETWORK_ERROR')
  }

  const contentType = response.headers.get('content-type') || ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) {
    const { message, code } = resolveMessage(payload, `请求失败（HTTP ${response.status}）`)
    if (response.status === 401 && !path.startsWith('/auth/login')) {
      window.dispatchEvent(new CustomEvent('lisa:unauthorized'))
    }
    throw new ApiError(response.status, message, code, payload)
  }
  return payload as T
}

export const http = {
  get: <T>(path: string, options?: RequestInit) => request<T>('GET', path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestInit) => request<T>('POST', path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestInit) => request<T>('PUT', path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestInit) => request<T>('PATCH', path, body, options),
  del: <T>(path: string, options?: RequestInit) => request<T>('DELETE', path, undefined, options),
}

export async function downloadFile(path: string, filename: string) {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${BASE}${path}`, { headers })
  if (!response.ok) {
    throw new ApiError(response.status, '导出失败，请稍后重试', 'EXPORT_FAILED')
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
