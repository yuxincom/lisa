<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const target = typeof route.query.from === 'string' ? route.query.from : ''
</script>

<template>
  <div class="page state-page">
    <div class="state-card panel">
      <div class="state-icon">
        <AppIcon name="lock" :size="30" />
      </div>
      <span class="state-code mono">403 · ABAC DENIED</span>
      <h1>权限不足</h1>
      <p>
        当前角色「{{ auth.roleLabel || auth.user?.role_label || '—' }}」无权访问该功能。
        权限策略由 ABAC 策略中心统一管控，越权请求已被拒绝并写入审计哈希链。
      </p>
      <div v-if="target" class="state-target">
        <span>请求路径</span>
        <code class="mono">{{ target }}</code>
      </div>
      <div class="state-actions">
        <button class="btn btn-ghost" type="button" @click="router.back()">
          <AppIcon name="chevronLeft" :size="15" />
          返回上一页
        </button>
        <button class="btn btn-primary" type="button" @click="router.push({ name: 'dashboard' })">
          <AppIcon name="dashboard" :size="15" />
          返回驾驶舱
        </button>
      </div>
      <div class="state-hint">
        <AppIcon name="info" :size="13" />
        如需开通权限，请联系系统管理员在 ABAC 矩阵中调整角色授权。
      </div>
    </div>
  </div>
</template>

<style scoped>
.state-page {
  display: grid;
  place-items: center;
  min-height: calc(100vh - 140px);
}

.state-card {
  width: min(560px, 100%);
  padding: clamp(28px, 5vw, 46px);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.state-icon {
  display: grid;
  place-items: center;
  width: 66px;
  height: 66px;
  border-radius: 20px;
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 32%, transparent);
  color: var(--danger);
  margin-bottom: 16px;
}

.state-code {
  font-size: 10.5px;
  letter-spacing: 0.18em;
  color: var(--danger);
  margin-bottom: 8px;
}

.state-card h1 {
  font-family: var(--font-display);
  font-size: clamp(24px, 3.4vw, 32px);
  font-weight: 720;
  letter-spacing: -0.01em;
}

.state-card p {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-2);
  max-width: 430px;
}

.state-target {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel-inset);
  font-size: 11px;
  color: var(--text-3);
  max-width: 100%;
  overflow: hidden;
}

.state-target code {
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.state-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 24px;
}

.state-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px dashed var(--border);
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
}

.state-hint svg {
  flex: none;
  color: var(--accent);
}
</style>
