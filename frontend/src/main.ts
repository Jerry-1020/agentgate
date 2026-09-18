import { createApp } from 'vue'
import App from './App.vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/main.scss'
import './revision/revision.scss'

createApp(App).use(ElementPlus).mount('#app')
