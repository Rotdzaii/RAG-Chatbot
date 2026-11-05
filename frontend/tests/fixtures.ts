import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

const user = {
  id: '11111111-1111-4111-8111-111111111111', email: 'chat@example.test',
  aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {},
  created_at: '2026-10-01T00:00:00Z',
}
const token = `${Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url')}.${Buffer.from(JSON.stringify({ sub: user.id, exp: 4102444800 })).toString('base64url')}.fixture`
const session = {
  access_token: token, refresh_token: 'fixture-refresh', token_type: 'bearer',
  expires_at: 4102444800, expires_in: 3600, user,
}

/** Isolated chat/auth fixtures; reject requests outside the local test servers. */
export async function fixture(page: Page) {
  await page.addInitScript(session => {
    localStorage.setItem('sb-127-auth-token', JSON.stringify(session))
  }, session)
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === 'http://127.0.0.1:5178') return route.continue()
    if (url.origin === 'http://127.0.0.1:48081') {
      if (url.pathname.endsWith('/logout')) return route.fulfill({ status: 204 })
      return route.fulfill({ json: url.pathname.endsWith('/user') ? user : session })
    }
    if (url.origin === 'http://127.0.0.1:48080') {
      expect(request.headers().authorization).toBe(`Bearer ${token}`)
      if (url.pathname === '/admin/knowledge-sources') return route.fulfill({ status: 403, json: { detail: 'Admin access required' } })
      if (url.pathname === '/conversations') return route.fulfill({ json: [] })
    }
    return route.abort()
  })
}
