import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/chart.js') || id.includes('node_modules/react-chartjs-2')) {
            return 'charts'
          }
          if (id.includes('node_modules/react-router-dom')) {
            return 'router'
          }
          if (
            id.includes('/src/components/workflow/') ||
            id.includes('/src/components/VerdictChips.tsx') ||
            id.includes('/src/utils.ts')
          ) {
            return 'workflow'
          }
          if (id.includes('node_modules')) {
            return 'vendor'
          }
        },
      },
    },
  },
})
