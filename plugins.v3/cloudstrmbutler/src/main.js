import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import Config from './Config.vue'
import Page from './Page.vue'

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        dark: false,
        colors: {
          background: '#fbfcfe',
          surface: '#ffffff',
          primary: '#2D6073',
          secondary: '#66758C',
          success: '#48A476',
          warning: '#D79A3F',
          error: '#B9633E',
        },
      },
      dark: {
        dark: true,
        colors: {
          background: '#121218',
          surface: '#181820',
          primary: '#7C4DFF',
          secondary: '#A5A2B1',
          success: '#59D39B',
          warning: '#E7B764',
          error: '#FF7F92',
        },
      },
    },
  },
})

const app = createApp(Page)
app.use(vuetify)
app.mount('#app')

export { Config, Page, vuetify }
