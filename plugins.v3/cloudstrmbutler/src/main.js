import { createApp } from 'vue'
import Config from './Config.vue'
import Page from './Page.vue'

const app = createApp({ template: '<div></div>' })
app.component('Config', Config)
app.component('Page', Page)

export { Config, Page }
