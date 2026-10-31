<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/composables/useAsync'
import AppIcon from '@/components/AppIcon.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const error = ref('')
const isDev = import.meta.env.DEV

const demoAccounts = [
  { username: 'commander', password: 'commander123', role: '生产指挥部', name: '王建国' },
  { username: 'planner', password: 'planner123', role: '计划员', name: '李静' },
  { username: 'dispatcher', password: 'dispatcher123', role: '调度员', name: '陈涛' },
  { username: 'engineer', password: 'engineer123', role: '工艺员', name: '赵磊' },
  { username: 'expert', password: 'expert123', role: '领域专家', name: '孙志远' },
  { username: 'admin', password: 'admin123', role: '系统管理员', name: '系统管理员' },
]

const canSubmit = computed(() => username.value.trim().length >= 2 && password.value.length >= 3 && !auth.loading)

function fill(account: (typeof demoAccounts)[number]) {
  username.value = account.username
  password.value = account.password
  error.value = ''
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    ui.success('登录成功', `欢迎回来，${auth.user?.name || auth.displayName}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    await router.replace(redirect.startsWith('/') ? redirect : '/dashboard')
  } catch (err) {
    error.value = errorMessage(err)
  }
}

onMounted(() => {
  ui.applyTheme()
  if (auth.token) router.replace('/dashboard')
})
</script>

<template>
  <div class="login-page">
    <div class="login-atmosphere">
      <div class="orbit orbit-a" />
      <div class="orbit orbit-b" />
      <div class="orbit orbit-c" />
      <div class="scan-line" />
    </div>

    <div class="login-theme"><ThemeToggle /></div>

    <section class="login-brand">
      <div class="brand-head">
        <span class="brand-emblem">
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <defs>
              <linearGradient id="login-grad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#f6bd67" />
                <stop offset="1" stop-color="#4fd1c5" />
              </linearGradient>
            </defs>
            <path d="M24 3 42 14v20L24 45 6 34V14Z" fill="none" stroke="url(#login-grad)" stroke-width="1.5" opacity=".9" />
            <path d="M24 11.5 35 17.7v13.6L24 37.5 13 31.3V17.7Z" fill="url(#login-grad)" opacity=".14" />
            <path d="M24 15 31 19v10l-7 4-7-4V19Z" fill="url(#login-grad)" opacity=".9" />
            <circle cx="24" cy="24" r="2.6" fill="#08111f" />
            <circle cx="24" cy="3" r="1.6" fill="#f6bd67" />
            <circle cx="42" cy="34" r="1.6" fill="#4fd1c5" />
            <circle cx="6" cy="34" r="1.2" fill="#f6bd67" opacity=".7" />
          </svg>
        </span>
        <div>
          <div class="brand-name">LISA</div>
          <div class="brand-cn">黎阳智能排产智能体</div>
        </div>
      </div>

      <h1 class="login-headline">
        把排产决策<br />
        变成<span>可追溯的工程系统</span>
      </h1>
      <p class="login-copy">
        面向航空发动机离散制造的三级智能体排产体系。运筹优化、规则引擎、知识图谱与大模型协同决策，
        每一份方案都有归因、有护栏、有签名、有兜底。
      </p>

      <div class="pillars">
        <div class="pillar">
          <span class="pillar-icon"><AppIcon name="audit" :size="16" /></span>
          <div><b>可追溯</b><small>PROV-O 血缘 · 哈希链审计</small></div>
        </div>
        <div class="pillar">
          <span class="pillar-icon"><AppIcon name="shield" :size="16" /></span>
          <div><b>可兜底</b><small>求解降级 · 规则兜底 · 人工接管</small></div>
        </div>
        <div class="pillar">
          <span class="pillar-icon"><AppIcon name="eye" :size="16" /></span>
          <div><b>可解释</b><small>白盒归因 · A/B/C 方案对比</small></div>
        </div>
        <div class="pillar">
          <span class="pillar-icon"><AppIcon name="lock" :size="16" /></span>
          <div><b>安全合规</b><small>ABAC · 写保护 · 数据不出内网</small></div>
        </div>
      </div>

      <div class="agent-ladder">
        <div class="ladder-item level-c">
          <span class="ladder-tag">C</span>
          <div><b>化合物级 · 全厂总控</b><small>MPS 拉动 · 多目标 · 夜间全量重排</small></div>
          <span class="ladder-state">写基线</span>
        </div>
        <div class="ladder-item level-m">
          <span class="ladder-tag">M</span>
          <div><b>分子级 · 跨工序协调</b><small>链式传播 · 齐套 · 涟漪影响评估</small></div>
          <span class="ladder-state">编排</span>
        </div>
        <div class="ladder-item level-a">
          <span class="ladder-tag">A</span>
          <div><b>原子级 · 单工序排产</b><small>七大工序域 · 有限产能 · 白盒建议</small></div>
          <span class="ladder-state">只读</span>
        </div>
      </div>

      <div class="brand-stats">
        <span><b class="num">108</b> 核心产品</span>
        <span><b class="num">3,024</b> 工序实例</span>
        <span><b class="num">68</b> 排产规则</span>
        <span><b class="num">14</b> 硬约束</span>
      </div>
    </section>

    <section class="login-panel-wrap">
      <div class="login-panel">
        <div class="panel-eyebrow">
          <span class="dot dot-live" /> 内网安全接入 · 生产环境
        </div>
        <h2 class="panel-title">登录调度工作台</h2>
        <p class="panel-sub">使用生产账号登录，所有操作将写入军工审计链。</p>

        <form class="login-form" @submit.prevent="submit">
          <label class="field">
            <span class="field-label">账号</span>
            <span class="input-shell">
              <AppIcon name="user" :size="16" />
              <input v-model="username" class="input" type="text" placeholder="请输入内网账号" autocomplete="username" autofocus />
            </span>
          </label>

          <label class="field">
            <span class="field-label">密码</span>
            <span class="input-shell">
              <AppIcon name="lock" :size="16" />
              <input
                v-model="password"
                class="input"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码"
                autocomplete="current-password"
              />
              <button type="button" class="eye-btn" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
                <AppIcon :name="showPassword ? 'eye' : 'lock'" :size="15" />
              </button>
            </span>
          </label>

          <div v-if="error" class="login-error">
            <AppIcon name="warning" :size="15" />
            {{ error }}
          </div>

          <button class="btn btn-primary btn-lg btn-block login-submit" type="submit" :disabled="!canSubmit">
            <span v-if="auth.loading" class="spinner" style="border-top-color: #1a1206" />
            <AppIcon v-else name="arrowRight" :size="17" />
            {{ auth.loading ? '正在校验身份…' : '进入工作台' }}
          </button>
        </form>

        <div class="login-footer">
          <div class="footer-line">
            <AppIcon name="shield" :size="13" />
            <span>ABAC 属性鉴权 · 越权访问拦截 100% · 写保护网关强制审批</span>
          </div>
          <div class="footer-line muted">
            <span>密级：内部资料</span>
            <span>·</span>
            <span>留痕：全链路审计</span>
            <span>·</span>
            <span>部署：私有化内网</span>
          </div>
        </div>

        <div v-if="isDev" class="demo-accounts">
          <div class="demo-title">开发环境内置账号 <span class="muted">点击快速填充</span></div>
          <div class="demo-grid">
            <button v-for="account in demoAccounts" :key="account.username" type="button" class="demo-chip" @click="fill(account)">
              <b>{{ account.role }}</b>
              <span>{{ account.username }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(400px, 0.85fr);
  gap: clamp(24px, 4vw, 72px);
  align-items: center;
  padding: clamp(26px, 5vh, 64px) clamp(22px, 5vw, 84px);
  overflow: hidden;
  z-index: 1;
}

.login-atmosphere {
  position: fixed;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  z-index: 0;
}

.orbit {
  position: absolute;
  border: 1px solid rgba(120, 165, 220, 0.1);
  border-radius: 50%;
}

.orbit-a {
  width: 700px;
  height: 700px;
  right: -240px;
  top: -260px;
  border-color: rgba(240, 164, 58, 0.1);
  animation: orbitSpin 60s linear infinite;
}

.orbit-a::before {
  content: '';
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  top: 18%;
  left: 8%;
  box-shadow: 0 0 18px var(--accent);
}

.orbit-b {
  width: 480px;
  height: 480px;
  right: -120px;
  top: -140px;
  animation: orbitSpin 44s linear infinite reverse;
}

.orbit-b::after {
  content: '';
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--teal);
  bottom: 12%;
  right: 12%;
  box-shadow: 0 0 14px var(--teal);
}

.orbit-c {
  width: 900px;
  height: 900px;
  left: -520px;
  bottom: -620px;
  border-color: rgba(79, 209, 197, 0.08);
}

@keyframes orbitSpin {
  to {
    transform: rotate(360deg);
  }
}

.scan-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(240, 164, 58, 0.18), transparent);
  animation: scan 9s ease-in-out infinite;
}

@keyframes scan {
  0%,
  100% {
    top: 12%;
    opacity: 0;
  }
  20% {
    opacity: 1;
  }
  80% {
    opacity: 1;
  }
  50% {
    top: 88%;
  }
}

.login-theme {
  position: fixed;
  top: 22px;
  right: 26px;
  z-index: 10;
}

.login-brand {
  position: relative;
  z-index: 1;
  max-width: 660px;
  animation: rise 0.7s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
}

.brand-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: clamp(20px, 3.4vh, 34px);
}

.brand-emblem {
  width: 50px;
  height: 50px;
}

.brand-name {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.2em;
  line-height: 1;
  background: linear-gradient(90deg, #f8c471, #f0a43a 40%, #7fe0d5);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand-cn {
  margin-top: 5px;
  font-size: 11px;
  color: var(--text-2);
  letter-spacing: 0.18em;
}

.login-headline {
  font-family: var(--font-display);
  font-size: clamp(32px, 4.1vw, 54px);
  line-height: 1.14;
  letter-spacing: -0.035em;
  font-weight: 760;
  color: var(--text);
}

.login-headline span {
  background: linear-gradient(92deg, #f6bd67 5%, #f0a43a 45%, #7fe0d5 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.login-copy {
  margin-top: 20px;
  max-width: 560px;
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--text-2);
}

.pillars {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 26px;
  max-width: 560px;
}

.pillar {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 13px;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 72%, transparent);
  backdrop-filter: blur(12px);
}

.pillar-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  flex: none;
}

.pillar b {
  display: block;
  font-size: 12.5px;
  font-weight: 640;
}

.pillar small {
  display: block;
  margin-top: 1px;
  font-size: 10px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-ladder {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 22px;
  max-width: 560px;
}

.ladder-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 12px;
  border-radius: 9px;
  border: 1px solid var(--border);
  border-left: 2px solid var(--tone);
  background: color-mix(in srgb, var(--panel) 55%, transparent);
}

.ladder-item.level-c {
  --tone: var(--accent);
}
.ladder-item.level-m {
  --tone: var(--blue);
}
.ladder-item.level-a {
  --tone: var(--teal);
}

.ladder-tag {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 12%, transparent);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 700;
  flex: none;
}

.ladder-item b {
  display: block;
  font-size: 12px;
  font-weight: 620;
}

.ladder-item small {
  display: block;
  font-size: 10px;
  color: var(--text-3);
}

.ladder-state {
  margin-left: auto;
  font-size: 9.5px;
  color: var(--tone);
  border: 1px solid color-mix(in srgb, var(--tone) 30%, transparent);
  border-radius: 99px;
  padding: 2px 8px;
  white-space: nowrap;
}

.brand-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 22px;
  margin-top: 26px;
  font-size: 10.5px;
  color: var(--text-3);
}

.brand-stats b {
  font-size: 16px;
  color: var(--text);
  margin-right: 4px;
  letter-spacing: -0.02em;
}

.login-panel-wrap {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: center;
  animation: rise 0.7s 0.1s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.login-panel {
  width: min(430px, 100%);
  padding: clamp(24px, 3.2vw, 34px);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-strong);
  background: color-mix(in srgb, var(--panel-solid) 86%, transparent);
  backdrop-filter: blur(24px);
  box-shadow: 0 40px 100px rgba(0, 0, 0, 0.38);
  position: relative;
  overflow: hidden;
}

.login-panel::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), var(--teal), transparent 85%);
}

.login-panel::after {
  content: '';
  position: absolute;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  right: -100px;
  top: -110px;
  background: radial-gradient(circle, rgba(240, 164, 58, 0.1), transparent 70%);
  pointer-events: none;
}

.panel-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.1em;
  color: var(--text-3);
  text-transform: uppercase;
  margin-bottom: 14px;
}

.panel-title {
  font-size: 24px;
  font-weight: 720;
  letter-spacing: -0.02em;
}

.panel-sub {
  margin-top: 7px;
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.6;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 15px;
  margin-top: 24px;
}

.input-shell {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
  background: var(--panel-inset);
  color: var(--text-3);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.input-shell:focus-within {
  border-color: var(--accent-line);
  box-shadow: var(--ring);
}

.input-shell .input {
  border: 0;
  background: transparent;
  padding-left: 0;
  padding-right: 0;
  box-shadow: none;
}

.eye-btn {
  border: 0;
  background: transparent;
  color: var(--text-3);
  padding: 4px;
  display: grid;
  place-items: center;
  border-radius: 5px;
}

.eye-btn:hover {
  color: var(--text-2);
}

.login-error {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 11.5px;
}

.login-submit {
  margin-top: 3px;
}

.login-footer {
  margin-top: 22px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.footer-line {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 10px;
  color: var(--text-3);
  line-height: 1.5;
}

.demo-accounts {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.demo-title {
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.08em;
  color: var(--text-3);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.demo-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.demo-chip {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 8px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: transparent;
  text-align: left;
  transition: all 0.15s ease;
}

.demo-chip:hover {
  border-color: var(--border-accent);
  background: var(--accent-soft);
}

.demo-chip b {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-2);
}

.demo-chip span {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--text-3);
}

@media (max-width: 1100px) {
  .login-page {
    grid-template-columns: 1fr;
    gap: 34px;
    padding-top: 76px;
    align-items: start;
  }
  .login-brand {
    max-width: none;
  }
  .login-panel-wrap {
    justify-content: flex-start;
  }
  .login-panel {
    width: 100%;
  }
  .login-headline {
    font-size: clamp(30px, 6vw, 42px);
  }
}

@media (max-width: 640px) {
  .login-page {
    padding: 70px 16px 34px;
    gap: 26px;
  }
  .login-theme {
    top: 16px;
    right: 16px;
  }
  .brand-head {
    margin-bottom: 18px;
  }
  .login-headline {
    font-size: 30px;
  }
  .login-copy {
    margin-top: 14px;
    font-size: 12.5px;
  }
  .pillars {
    grid-template-columns: 1fr 1fr;
    gap: 7px;
    margin-top: 18px;
  }
  .pillar {
    padding: 9px;
  }
  .pillar small {
    display: none;
  }
  .agent-ladder {
    display: none;
  }
  .brand-stats {
    margin-top: 18px;
    gap: 14px;
  }
  .brand-stats b {
    font-size: 14px;
  }
  .login-panel {
    padding: 20px 18px;
    backdrop-filter: blur(16px);
  }
  .demo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
