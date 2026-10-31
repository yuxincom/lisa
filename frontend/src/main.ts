import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useUiStore } from './stores/ui'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

const ui = useUiStore(pinia)
ui.applyTheme()

app.use(router)

router.isReady().then(() => {
  app.mount('#app')
})
