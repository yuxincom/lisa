<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
</script>

<template>
  <div class="page state-page">
    <div class="state-card panel">
      <div class="state-glyph">
        <span class="glyph-404 mono">404</span>
        <span class="glyph-ring" />
      </div>
      <span class="state-code mono">ROUTE NOT FOUND</span>
      <h1>页面不存在</h1>
      <p>请求的页面可能已被移动或尚未开放。请检查地址，或返回驾驶舱继续工作。</p>
      <div class="state-target">
        <span>请求路径</span>
        <code class="mono">{{ route.fullPath }}</code>
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

.state-glyph {
  position: relative;
  display: grid;
  place-items: center;
  width: 128px;
  height: 128px;
  margin-bottom: 20px;
}

.glyph-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1px dashed var(--border-strong);
  background: radial-gradient(circle, var(--accent-soft), transparent 68%);
  animation: slowSpin 26s linear infinite;
}

.glyph-404 {
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 720;
  color: var(--accent);
  letter-spacing: -0.03em;
}

@keyframes slowSpin {
  to {
    transform: rotate(360deg);
  }
}

.state-code {
  font-size: 10.5px;
  letter-spacing: 0.18em;
  color: var(--text-3);
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
  max-width: 420px;
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
</style>
