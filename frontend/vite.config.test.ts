// @vitest-environment node
import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'

const deployment = JSON.parse(readFileSync(new URL('./vercel.json', import.meta.url), 'utf8'))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

it('serves the deployed security headers in preview', async () => {
  const { default: config } = await import('./vite.config')
  const expected = Object.fromEntries(
    deployment.headers[0].headers.map(({ key, value }: { key: string; value: string }) => [key, value]),
  )
  expect(config.preview?.headers).toEqual(expected)
  expect(expected['Content-Security-Policy']).toContain("img-src 'self' data: https:")
  expect(expected['Content-Security-Policy']).not.toContain('blob:')
})

it('proxies candidate HTTP and WebSocket requests in preview and development', async () => {
  vi.stubEnv('VITE_API_PROXY_TARGET', 'https://candidate.example.test')
  const { default: config } = await import('./vite.config')
  expect(config.preview?.proxy).toEqual({
    '/api': { target: 'https://candidate.example.test', changeOrigin: true, ws: true },
  })
  expect(config.server?.proxy).toEqual(config.preview?.proxy)
})
