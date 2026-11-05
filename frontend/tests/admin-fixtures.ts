import { expect } from '@playwright/test'
import type { Page, Request } from '@playwright/test'

const user = { id: '11111111-1111-4111-8111-111111111111', email: 'admin@example.test', aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {}, created_at: '2026-10-01T00:00:00Z' }
const token = `${Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url')}.${Buffer.from(JSON.stringify({ sub: user.id, exp: 4102444800 })).toString('base64url')}.fixture`
const session = { access_token: token, refresh_token: 'fixture-refresh', token_type: 'bearer', expires_at: 4102444800, expires_in: 3600, user }
const file = { is_active: true, id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', filename: 'Chương trình Marketing.pdf', mime_type: 'application/pdf', source_type: 'file', source_url: null, category: null as string | null, audience: null as string | null, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-30T08:30:00Z', last_checked_at: null, chunk_count: 17 }
const urlSource = { ...file, id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', filename: 'Tài chính – Ngân hàng', source_type: 'url', source_url: 'https://www.vlu.edu.vn/academics/majors/tai-chinh-ngan-hang', mime_type: 'text/html', chunk_count: 26, last_checked_at: '2026-11-01T00:00:00Z' }
const notification = { id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', document_id: urlSource.id, source_url: urlSource.source_url, baseline_hash: 'a'.repeat(64), observed_hash: 'b'.repeat(64), detected_at: '2026-11-01T00:00:00Z', read_at: null as string | null }

async function fixture(page: Page, options: { auth?: boolean; denied?: number; empty?: boolean; many?: boolean; manyNotifications?: boolean } = {}) {
  const requests: Request[] = []
  const sources = options.empty ? [] : [structuredClone(file), structuredClone(urlSource)]
  if (options.many) for (let index = 0; index < 48; index++) sources.push({ ...structuredClone(file), id: `90000000-0000-4000-8000-${String(index).padStart(12, '0')}`, filename: `Tài liệu kiểm thử ${index}.pdf` })
  const notifications = options.empty ? [] : [structuredClone(notification)]
  if (options.manyNotifications) for (let index = 0; index < 20; index++) notifications.push({ ...structuredClone(notification), id: `80000000-0000-4000-8000-${String(index).padStart(12, '0')}` })
  let refreshStatus: 'updated' | 'unchanged' = 'unchanged'
  let mutationError = 0
  let listError = 0
  let holdList: Promise<void> | undefined
  let holdMutation: Promise<void> | undefined
  let holdPermission: Promise<void> | undefined
  let permissionError: number | 'network' = 0
  let nextSession = session
  const validTokens = new Set([token])
  await page.addInitScript(({ session, authenticated }) => {
    if (authenticated && !sessionStorage.getItem('admin-fixture-seeded')) {
      localStorage.setItem('sb-127-auth-token', JSON.stringify(session))
      sessionStorage.setItem('admin-fixture-seeded', 'true')
    }
  }, { session, authenticated: options.auth !== false })
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === 'http://127.0.0.1:5178') { await route.continue(); return }
    if (url.origin === 'http://127.0.0.1:48081') {
      if (url.pathname.endsWith('/logout')) { await route.fulfill({ status: 204 }); return }
      await route.fulfill({ json: request.url().includes('/user') ? user : nextSession }); return
    }
    if (url.origin !== 'http://127.0.0.1:48080') { await route.abort(); return }
    requests.push(request)
    expect(validTokens.has(request.headers().authorization?.replace('Bearer ', ''))).toBe(true)
    if (url.pathname === '/admin/knowledge-sources' && url.searchParams.get('limit') === '1') {
      if (holdPermission) await holdPermission
      if (permissionError === 'network') { await route.abort(); return }
      if (permissionError) { await route.fulfill({ status: permissionError, json: { detail: 'permission unavailable' } }); return }
    }
    if (options.denied && url.pathname.startsWith('/admin')) { await route.fulfill({ status: options.denied, json: { detail: 'denied' } }); return }
    const isMutation = request.method() !== 'GET'
    if (isMutation && holdMutation) await holdMutation
    if (isMutation && mutationError) { await route.fulfill({ status: mutationError, json: { detail: 'private raw provider error' } }); return }
    if (url.pathname === '/admin/knowledge-sources' && request.method() === 'GET') {
      if (holdList && url.searchParams.get('limit') !== '1') await holdList
      if (listError && url.searchParams.get('limit') !== '1') { await route.fulfill({ status: listError, json: { detail: 'unavailable' } }); return }
      const type = url.searchParams.get('source_type')
      const category = url.searchParams.get('category')?.normalize('NFC').trim().replace(/\s+/g, ' ')
      const audience = url.searchParams.get('audience')?.normalize('NFC').trim().replace(/\s+/g, ' ')
      const active = url.searchParams.get('is_active')
      const filtered = sources.filter(item => (active == null || item.is_active === (active === 'true')) && (!type || item.source_type === type) && (category == null || item.category === category) && (audience == null || item.audience === audience))
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      await route.fulfill({ json: { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset } }); return
    }
    if (url.pathname === '/documents' || url.pathname === '/admin/knowledge-sources/url') {
      expect(request.method()).toBe('POST')
      const normalize = (value?: string | null) => value?.normalize('NFC').trim().replace(/\s+/g, ' ') || null
      const multipartField = (key: string) => request.postDataBuffer()?.toString().match(new RegExp(`name="${key}"\\r\\n\\r\\n([^\\r\\n]*)`))?.[1]
      if (url.pathname === '/documents') {
        expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=')
        expect(request.postDataBuffer()?.toString()).toContain('name="file"')
      } else expect(request.postDataJSON()).toMatchObject({ url: 'https://www.vlu.edu.vn/new-source' })
      const name = url.pathname === '/documents' ? request.postDataBuffer()!.toString().match(/filename="([^"]+)"/)![1] : 'new-source'
      const added = { ...structuredClone(file), id: `70000000-0000-4000-8000-${String(sources.length).padStart(12, '0')}`, filename: name,
        source_url: url.pathname === '/documents' ? null : request.postDataJSON().url as string,
        category: normalize(url.pathname === '/documents' ? multipartField('category') : request.postDataJSON().category),
        audience: normalize(url.pathname === '/documents' ? multipartField('audience') : request.postDataJSON().audience),
        mime_type: name.endsWith('.pdf') ? 'application/pdf' : 'text/plain', source_type: url.pathname === '/documents' ? 'file' : 'url' }
      sources.push(added)
      await route.fulfill({ status: 201, json: { document_id: added.id, filename: added.filename, chunk_count: 1 } }); return
    }
    if (url.pathname.endsWith('/file')) {
      expect(request.method()).toBe('PUT')
      expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=')
      const source = sources.find(item => url.pathname.includes(item.id))!
      source.filename = request.postDataBuffer()!.toString().match(/filename="([^"]+)"/)![1]
      source.mime_type = source.filename.endsWith('.pdf') ? 'application/pdf' : 'text/plain'
      await route.fulfill({ json: { document_id: source.id, filename: source.filename, chunk_count: 1, status: 'updated' } }); return
    }
    if (url.pathname.endsWith('/status')) {
      expect(request.method()).toBe('PATCH')
      const source = sources.find(item => url.pathname.includes(item.id))!
      source.is_active = request.postDataJSON().is_active
      await route.fulfill({ json: { id: source.id, is_active: source.is_active, updated_at: source.updated_at } }); return
    }
    if (url.pathname.endsWith('/metadata')) {
      expect(request.method()).toBe('PATCH')
      const source = sources.find(item => url.pathname.includes(item.id))!
      const body = request.postDataJSON()
      for (const key of ['category', 'audience'] as const) {
        if (Object.hasOwn(body, key)) source[key] = body[key]?.normalize('NFC').trim().replace(/\s+/g, ' ') || null
      }
      await route.fulfill({ json: { id: source.id, category: source.category, audience: source.audience, updated_at: source.updated_at } }); return
    }
    if (url.pathname.endsWith('/refresh')) {
      expect(request.method()).toBe('POST')
      await route.fulfill({ json: { document_id: urlSource.id, filename: urlSource.filename, chunk_count: 26, status: refreshStatus } }); return
    }
    if (request.method() === 'GET' && /^\/admin\/knowledge-sources\/[^/]+$/.test(url.pathname)) {
      const source = sources.find(item => url.pathname.endsWith(item.id))
      await route.fulfill({ status: source ? 200 : 404, json: source ?? { detail: 'not found' } }); return
    }
    if (request.method() === 'DELETE') {
      sources.splice(sources.findIndex(item => url.pathname.endsWith(item.id)), 1)
      await route.fulfill({ status: 204 }); return
    }
    if (url.pathname === '/admin/source-change-notifications') {
      expect(request.method()).toBe('GET')
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      await route.fulfill({ json: notifications.filter(item => url.searchParams.get('unread_only') !== 'true' || !item.read_at).slice(offset, offset + limit) }); return
    }
    if (url.pathname.endsWith('/read')) {
      expect(request.method()).toBe('POST')
      expect(request.postData()).toBeNull()
      const item = notifications.find(item => url.pathname.includes(item.id))!
      item.read_at ??= '2026-11-02T02:00:00Z'
      await route.fulfill({ json: item }); return
    }
    if (url.pathname === '/conversations') { await route.fulfill({ json: options.many ? Array.from({ length: 60 }, (_, index) => ({ id: `history-${index}`, title: `Hội thoại kiểm thử ${index}`, is_pinned: false, created_at: file.created_at, updated_at: file.updated_at })) : [] }); return }
    await route.abort()
  })
  return {
    requests,
    failMutations: (status: number) => { mutationError = status },
    failLists: (status: number) => { listError = status },
    refreshStatus: (status: 'updated' | 'unchanged') => { refreshStatus = status },
    hold: (promise?: Promise<void>) => { holdMutation = promise },
    holdLists: (promise?: Promise<void>) => { holdList = promise },
    holdPermission: (promise?: Promise<void>) => { holdPermission = promise },
    failPermission: (status: number | 'network') => { permissionError = status },
    refreshSession: async () => {
      const refreshedToken = `${token.split('.').slice(0, 2).join('.')}.refreshed-fixture`
      nextSession = { ...session, access_token: refreshedToken }
      validTokens.add(refreshedToken)
      await page.evaluate(async () => {
        const modulePath = '/src/auth/supabase.ts'
        const { supabase } = await import(modulePath)
        const { error } = await supabase.auth.refreshSession()
        if (error) throw error
      })
    },
  }
}



export { fixture, file, urlSource }
