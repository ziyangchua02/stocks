import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard is local-only: the dev server proxies the API so the browser
// never needs a second origin and no API key is ever exposed to the page.
export default defineConfig({
  // Relative, so the same bundle works at a domain root or under /<repo>/ on
  // GitHub Pages. Routing is hash-based, which Pages serves without rewrites.
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: { environment: 'node', include: ['src/**/*.test.js'] },
})
