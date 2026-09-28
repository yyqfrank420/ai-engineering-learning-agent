import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
const deployment = JSON.parse(readFileSync(new URL('./vercel.json', import.meta.url), 'utf8')) as {
  headers: { source: string; headers: { key: string; value: string }[] }[]
}
if (deployment.headers?.length !== 1 || deployment.headers[0].source !== '/(.*)') {
  throw new Error('Vite preview requires one global header rule from vercel.json')
}
const productionHeaders = Object.fromEntries(
  deployment.headers[0].headers.map(({ key, value }) => [key, value]),
)
const apiProxy = {
  '/api': {
    target: apiProxyTarget,
    changeOrigin: true,
    ws: true,
  },
}

export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: {
    headers: productionHeaders,
    proxy: apiProxy,
  },
})
