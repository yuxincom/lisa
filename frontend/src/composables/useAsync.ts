import { onMounted, ref, type Ref } from 'vue'
import { ApiError } from '@/api/client'
import { useUiStore } from '@/stores/ui'

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '未知错误'
}

export function useAsync<T>(loader: () => Promise<T>, options: { immediate?: boolean; silent?: boolean } = {}) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref('')
  const ui = useUiStore()

  async function run(showToast = false): Promise<T | null> {
    loading.value = true
    error.value = ''
    try {
      data.value = await loader()
      return data.value
    } catch (err) {
      error.value = errorMessage(err)
      if (showToast && !options.silent) ui.error('数据加载失败', error.value)
      return null
    } finally {
      loading.value = false
    }
  }

  if (options.immediate !== false) {
    onMounted(() => {
      void run()
    })
  }

  return { data, loading, error, run, refresh: () => run(false) }
}
