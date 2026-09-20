import { createApp } from 'vue';
import App from './App.vue';
import { pinia } from './stores/index';
import { router } from './router/index';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import './styles/main.scss';
import './styles/revision.scss';

createApp(App).use(pinia).use(router).use(ElementPlus).mount('#app');
