import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { join } from 'node:path'
import { mkdir, readFile } from 'node:fs/promises'

import { fixture, file, urlSource } from './admin-fixtures'
const reviewDir = process.env.ADMIN_REVIEW_DIR ?? '../data/admin-review'

async function signIn(page: Page) {
  await page.getByLabel('Email', { exact: true }).fill('admin@gmail.com')
  await page.getByLabel('Mật khẩu', { exact: true }).fill('fixture-password')
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click()
}

async function sourceAction(page: Page, filename: string, label: string) {
  await page.getByRole('button', { name: `Thao tác với ${filename}`, exact: true }).click()
  await page.getByRole('menu', { name: `Thao tác với ${filename}`, exact: true }).getByRole('menuitem', { name: label, exact: true }).click()
}

async function openAdd(page: Page, kind = 'file') {
  await page.getByRole('button', { name: '+ Thêm nguồn', exact: true }).click()
  await page.getByRole('tab', { name: kind === 'url' ? 'Nhập URL' : 'Tải tệp lên', exact: true }).click()
  return page.getByRole('dialog')
}

async function filter(page: Page, values: { type?: string; active?: string; category?: string; audience?: string }) {
  await page.getByRole('button', { name: /^Bộ lọc/ }).click()
  const dialog = page.getByRole('dialog')
  if (values.type !== undefined) await dialog.getByLabel('Loại nguồn', { exact: true }).selectOption(values.type)
  if (values.active !== undefined) await dialog.getByLabel('Trạng thái nguồn', { exact: true }).selectOption(values.active)
  if (values.category !== undefined || values.audience !== undefined) {
    if (!(await dialog.locator('details').getAttribute('open') !== null)) await dialog.locator('summary').click()
    if (values.category !== undefined) await dialog.getByLabel('Phân loại', { exact: true }).fill(values.category)
    if (values.audience !== undefined) await dialog.getByLabel('Đối tượng', { exact: true }).fill(values.audience)
    await expect(dialog.getByLabel('Đối tượng', { exact: true })).toBeVisible()
  }
  await dialog.getByRole('button', { name: 'Áp dụng', exact: true }).click()
}

test('retired notification bookmark opens sources without notification links or API requests on desktop and mobile', async ({ page }) => {
  const mock = await fixture(page)
  await page.goto('/admin/notifications')
  await expect(page).toHaveURL(/\/admin\/sources$/)
  await expect(page.getByRole('heading', { name: 'Quản lý nguồn', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Thông báo', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '+ Thêm nguồn', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
  const navigation = page.getByRole('dialog', { name: 'Điều hướng quản trị' })
  await expect(navigation.getByRole('link', { name: 'Thông báo', exact: true })).toHaveCount(0)
  await navigation.getByRole('link', { name: 'Quản lý nguồn', exact: true }).click()
  await expect(navigation).toHaveCount(0)
  expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/admin/source-change-notifications'))).toBe(false)
})

test('API mock: reference catalog, real detail request, filters and keyboard menu', async ({ page }) => {
  const mock = await fixture(page)
  await page.goto('/admin/sources')
  await expect(page.getByRole('heading', { name: file.filename })).toBeVisible()
  await page.getByRole('button', { name: file.filename, exact: true }).click()
  await expect(page.getByRole('dialog').getByText(file.id, { exact: true })).toBeVisible()
  expect(mock.requests.some(request => new URL(request.url()).pathname.endsWith(file.id))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: file.filename, exact: true })).toBeFocused()
  await filter(page, { type: 'file', active: 'true' })
  await expect(page.getByRole('heading', { name: urlSource.filename })).toHaveCount(0)
  await expect(page.getByLabel('Điều kiện đang áp dụng')).toContainText('PDF / TXT')
  await page.getByRole('button', { name: 'Bỏ lọc Loại nguồn' }).click()
  await expect(page.getByRole('heading', { name: urlSource.filename })).toBeVisible()
  await filter(page, { category: 'missing', audience: 'staff' })
  await expect(page.getByRole('heading', { name: 'Chưa có nguồn trong danh sách này' })).toBeVisible()
  await page.getByRole('button', { name: /^Bộ lọc/ }).click()
  await page.getByRole('button', { name: 'Xóa bộ lọc', exact: true }).click()
  await expect(page.getByRole('heading', { name: file.filename })).toBeVisible()
  const more = page.getByRole('button', { name: `Thao tác với ${file.filename}` })
  await more.focus(); await page.keyboard.press('ArrowDown')
  const items = page.getByRole('menu').getByRole('menuitem')
  await expect(items.first()).toBeFocused()
  await page.keyboard.press('End'); await expect(items.last()).toBeFocused()
  await expect(items.last()).toHaveText('Xóa nguồn')
  await page.keyboard.press('Escape'); await expect(more).toBeFocused()
})

for (const kind of ['pdf', 'txt', 'url']) {
  test(`API mock: ${kind} upload validation pending error retry optional fields and list update`, async ({ page }) => {
    const mock = await fixture(page, { empty: true })
    await page.goto('/admin/sources')
    const dialog = await openAdd(page, kind)
    if (kind === 'url') await dialog.getByLabel('Địa chỉ nguồn').fill('https://www.vlu.edu.vn/new-source')
    else {
      await dialog.getByRole('button', { name: 'Thêm nguồn', exact: true }).click()
      await expect(dialog.getByRole('alert')).toContainText('Hãy chọn tài liệu')
      await dialog.getByLabel('Chọn tài liệu', { exact: true }).setInputFiles({ name: `new.${kind}`, mimeType: kind === 'pdf' ? 'application/pdf' : 'text/plain', buffer: Buffer.from('isolated fixture') })
    }
    await dialog.locator('summary').click()
    await dialog.getByLabel('Phân loại', { exact: true }).fill('policy')
    await dialog.getByLabel('Đối tượng', { exact: true }).fill('staff')
    mock.failMutations(503)
    let release!: () => void
    mock.hold(new Promise<void>(resolve => { release = resolve }))
    await dialog.getByRole('button', { name: 'Thêm nguồn', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText('Đang xử lý nguồn')
    await expect(dialog.getByRole('button', { name: 'Đang xử lý…', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('button', { name: 'Đóng hộp thoại' })).toBeDisabled()
    release(); await expect(dialog.getByRole('alert')).toContainText('Dịch vụ tạm thời chưa sẵn sàng.')
    mock.hold(); mock.failMutations(0)
    await dialog.getByRole('button', { name: 'Thêm nguồn', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('heading', { name: kind === 'url' ? 'new-source' : `new.${kind}`, exact: true })).toBeVisible()
    const request = mock.requests.filter(request => request.method() === 'POST').at(-1)!
    if (kind === 'url') expect(request.postDataJSON()).toEqual({ url: 'https://www.vlu.edu.vn/new-source', category: 'policy', audience: 'staff' })
    else {
      expect(request.postDataBuffer()?.toString()).toContain('name="category"\r\n\r\npolicy')
      expect(request.postDataBuffer()?.toString()).toContain(`filename="new.${kind}"`)
    }
  })
}

test('API mock: disable confirm, replace PDF TXT and refresh preserve inactive status, errors and reenable', async ({ page }) => {
  const mock = await fixture(page)
  await page.goto('/admin/sources')
  for (const source of [file, urlSource]) {
    await sourceAction(page, source.filename, 'Tắt nguồn')
    await expect(page.getByRole('dialog')).toContainText('câu trả lời đã lưu không tự được sửa')
    expect(mock.requests.filter(request => request.url().endsWith('/status'))).toHaveLength(source === file ? 0 : 1)
    await page.getByRole('dialog').getByRole('button', { name: 'Tắt nguồn', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await expect(page.locator('.admin-source-status--inactive')).toHaveCount(2)
  let filename = file.filename
  for (const kind of ['pdf', 'txt']) {
    await sourceAction(page, filename, 'Thay file')
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Cập nhật giữ nguyên trạng thái tắt')
    await dialog.getByLabel('Tài liệu thay thế', { exact: true }).setInputFiles({ name: `revised.${kind}`, mimeType: kind === 'pdf' ? 'application/pdf' : 'text/plain', buffer: Buffer.from('fixture') })
    mock.failMutations(503)
    await dialog.getByRole('button', { name: 'Thay file', exact: true }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    mock.failMutations(0)
    await dialog.getByRole('button', { name: 'Thay file', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    filename = `revised.${kind}`
    await expect(page.getByRole('heading', { name: filename, exact: true })).toBeVisible()
    await expect(page.locator('.admin-source-status--inactive')).toHaveCount(2)
  }
  await sourceAction(page, urlSource.filename, 'Cập nhật URL')
  mock.failMutations(502)
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật URL', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Không tải được nguồn URL.')
  mock.failMutations(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật URL', exact: true }).click()
  await expect(page.getByText('Nội dung URL không thay đổi.', { exact: true })).toBeVisible()
  mock.refreshStatus('updated')
  await sourceAction(page, urlSource.filename, 'Cập nhật URL')
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật URL', exact: true }).click()
  await expect(page.getByText('Đã cập nhật nội dung URL và nguồn trả lời.', { exact: true })).toBeVisible()
  await filter(page, { active: 'false' })
  await sourceAction(page, filename, 'Bật nguồn')
  await page.getByRole('dialog').getByRole('button', { name: 'Bật nguồn', exact: true }).click()
  await expect(page.getByRole('heading', { name: filename, exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Bỏ lọc Trạng thái' }).click()
  await expect(page.locator('.admin-source-status--active')).toHaveCount(1)
})

test('API mock: edit touched metadata, clear null, open stored URL and confirm deletion without unsupported file endpoint', async ({ page }) => {
  const mock = await fixture(page)
  await page.goto('/admin/sources')
  await sourceAction(page, file.filename, 'Sửa thông tin')
  let dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Lưu thông tin' })).toBeDisabled()
  await dialog.getByLabel('Phân loại', { exact: true }).fill(' policy ')
  await dialog.getByLabel('Đối tượng', { exact: true }).fill('staff')
  await dialog.getByRole('button', { name: 'Lưu thông tin' }).click()
  await expect(dialog).toHaveCount(0)
  await filter(page, { category: 'policy', audience: 'staff' })
  await expect(page.getByRole('heading', { name: urlSource.filename })).toHaveCount(0)
  await sourceAction(page, file.filename, 'Sửa thông tin')
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Đối tượng', { exact: true }).fill('')
  await dialog.getByRole('button', { name: 'Lưu thông tin' }).click()
  await expect(page.getByRole('heading', { name: 'Chưa có nguồn trong danh sách này' })).toBeVisible()
  expect(mock.requests.filter(request => request.method() === 'PATCH').at(-1)!.postDataJSON()).toEqual({ audience: null })
  await filter(page, { category: '', audience: '' })
  await page.getByRole('button', { name: `Thao tác với ${file.filename}`, exact: true }).click()
  await expect(page.getByRole('menu').getByRole('menuitem', { name: 'Mở bản gốc', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.evaluate(() => {
    window.open = (url, target, features) => {
      document.documentElement.dataset.openedSource = JSON.stringify({ url, target, features })
      return null
    }
  })
  await sourceAction(page, urlSource.filename, 'Mở URL gốc')
  expect(JSON.parse(await page.evaluate(() => document.documentElement.dataset.openedSource!))).toEqual({ url: urlSource.source_url, target: '_blank', features: 'noopener,noreferrer' })
  expect(mock.requests.some(request => request.url().endsWith('/original'))).toBe(false)
  await sourceAction(page, file.filename, 'Xóa nguồn')
  await expect(page.getByRole('button', { name: 'Giữ lại' })).toBeFocused()
  await page.keyboard.press('Escape')
  expect(mock.requests.filter(request => request.method() === 'DELETE')).toHaveLength(0)
  await sourceAction(page, file.filename, 'Xóa nguồn')
  mock.failMutations(503)
  await page.getByRole('dialog').getByRole('button', { name: 'Xóa nguồn', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
  mock.failMutations(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Xóa nguồn', exact: true }).click()
  await expect(page.getByRole('heading', { name: file.filename })).toHaveCount(0)
})

test('API mock: loading and safe list errors, URL validation, 401/403 remove controls', async ({ browser }) => {
  for (const status of [401, 403]) {
    const page = await browser.newPage()
    const mock = await fixture(page)
    mock.failLists(503)
    await page.goto('http://127.0.0.1:5178/admin/sources')
    await expect(page.getByRole('alert')).toBeVisible()
    mock.failLists(0); await page.getByRole('button', { name: 'Thử tải lại' }).click()
    const dialog = await openAdd(page, 'url')
    await dialog.getByLabel('Địa chỉ nguồn').fill('https://example.com/test')
    await dialog.getByRole('button', { name: 'Thêm nguồn', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Dùng URL HTTPS thuộc')
    await dialog.getByLabel('Địa chỉ nguồn').fill('https://www.vlu.edu.vn/new-source')
    mock.failMutations(status)
    await dialog.getByRole('button', { name: 'Thêm nguồn', exact: true }).click()
    await expect(page.getByRole('heading', { name: status === 401 ? 'Phiên đăng nhập đã hết hạn' : 'Bạn chưa có quyền quản trị' })).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.close()
  }
})

test('guest redirected, nonadmin forbidden and expired session can log in again', async ({ browser }) => {
  for (const denied of [0, 403, 401]) {
    const page = await browser.newPage()
    const mock = await fixture(page, { auth: denied !== 0, denied })
    await page.goto('http://127.0.0.1:5178/admin/sources')
    if (!denied) { await expect(page).toHaveURL(/\/login$/); expect(mock.requests).toHaveLength(0) }
    if (denied === 403) {
      await expect(page.getByRole('heading', { name: 'Bạn chưa có quyền quản trị' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Thêm nguồn' })).toHaveCount(0)
    }
    if (denied === 401) {
      await expect(page.getByRole('heading', { name: 'Phiên đăng nhập đã hết hạn' })).toBeVisible()
      await page.getByRole('button', { name: 'Đăng nhập lại' }).click()
      await expect(page).toHaveURL(/\/login$/)
    }
    await page.close()
  }
})

test('returning to chat preserves existing authenticated chat and history UI', async ({ page }) => {
  const mock = await fixture(page)
  await page.goto('/admin/sources')
  await page.getByRole('link', { name: 'Về trò chuyện', exact: true }).click()
  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.getByRole('heading', { name: 'Bạn cần tìm thông tin gì tại Văn Lang?' })).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Lịch sử trò chuyện', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cuộc trò chuyện mới', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Gửi câu hỏi' })).toBeDisabled()
  expect(mock.requests.some(request => new URL(request.url()).pathname === '/conversations')).toBe(true)
  await expect(page.getByRole('link', { name: 'Mở trang quản trị' })).toBeVisible()
  await mock.refreshSession()
  await expect(page.getByRole('link', { name: 'Mở trang quản trị' })).toBeVisible()
  await expect(page).toHaveURL(/\/chat$/)
  await page.getByRole('link', { name: 'Mở trang quản trị' }).click()
  await expect(page.getByRole('heading', { name: 'Quản lý nguồn', exact: true })).toBeVisible()
})

test('API mock: admin can open history and submit an SSE follow-up after returning to chat', async ({ page }) => {
  await fixture(page)
  const conversation = { id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', title: 'Hội thoại đã lưu', is_pinned: false, created_at: file.created_at, updated_at: file.updated_at }
  const source = { citation: 1, chunk_id: 'chunk-1', document_id: file.id, filename: 'legacy.txt', chunk_index: 0, cosine_distance: .1 }
  await page.route('**/conversations', route => route.fulfill({ json: [conversation] }))
  await page.route('**/conversations/*/messages', route => route.fulfill({ json: [
    { id: 'user-old', conversation_id: conversation.id, role: 'user', content: 'Câu hỏi cũ', citations: null, created_at: file.created_at },
    { id: 'answer-old', conversation_id: conversation.id, role: 'assistant', content: 'Trả lời cũ [1].', citations: [source], created_at: file.created_at },
  ] }))
  await page.route('**/questions/stream', route => {
    expect(route.request().headers().authorization).toMatch(/^Bearer /)
    const body = route.request().postDataJSON()
    expect(body.conversation_id).toBe(conversation.id)
    expect(body.question).toBe('Hỏi tiếp')
    return route.fulfill({ contentType: 'text/event-stream', body: `event: result\ndata: ${JSON.stringify({ request_id: body.request_id, response: { answer: 'Trả lời tiếp [1].', sources: [source], conversation_id: conversation.id } })}\n\n` })
  })
  await page.goto('/admin')
  await page.getByRole('link', { name: 'Về trò chuyện', exact: true }).click()
  await page.getByRole('button', { name: conversation.title, exact: true }).click()
  await expect(page.locator('.chat-turn')).toHaveCount(1)
  await expect(page.getByText('Trả lời cũ [1].', { exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true }).fill('Hỏi tiếp')
  await page.getByRole('button', { name: 'Gửi câu hỏi', exact: true }).click()
  await expect(page.locator('.chat-turn')).toHaveCount(2)
  await expect(page.getByText('Trả lời tiếp [1].', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Mở trang quản trị', exact: true })).toBeVisible()
})

test('API mock: admin and ordinary chat user can retry logout and cannot reopen protected content', async ({ browser }) => {
  for (const denied of [0, 403]) {
    const page = await browser.newPage()
    await fixture(page, { denied })
    let failLogout = true
    await page.route('http://127.0.0.1:48081/**/logout*', route => {
      const status = failLogout ? 400 : 204
      failLogout = false
      return status === 204 ? route.fulfill({ status }) : route.fulfill({ status, json: { message: 'fixture logout error' } })
    })
    await page.goto(`http://127.0.0.1:5178/${denied ? 'chat' : 'admin'}`)
    await page.getByRole('button', { name: 'Đăng xuất', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Không thể đăng xuất.')
    await expect(page.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: 'Đăng xuất', exact: true }).click()
    await expect(page).toHaveURL(/\/login$/)
    expect(await page.evaluate(() => localStorage.getItem('sb-127-auth-token'))).toBeNull()
    await page.goto('http://127.0.0.1:5178/admin')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Quản lý nguồn', exact: true })).toHaveCount(0)
    await page.close()
  }
})


test('login waits for backend permission, sends admin to admin and ordinary user to chat', async ({ browser }) => {
  for (const denied of [0, 403]) {
    const page = await browser.newPage()
    const mock = await fixture(page, { auth: false, denied })
    let release!: () => void
    mock.holdPermission(new Promise<void>(resolve => { release = resolve }))
    await page.goto('http://127.0.0.1:5178/login')
    await signIn(page)
    await expect(page.getByText('Đang xác nhận quyền truy cập…', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Quản lý nguồn', exact: true })).toHaveCount(0)
    expect(mock.requests.filter(request => new URL(request.url()).pathname === '/conversations')).toHaveLength(0)
    release()
    await expect(page).toHaveURL(denied ? /\/chat$/ : /\/admin\/sources$/)
    await expect(page.getByRole('heading', { name: denied ? 'Bạn cần tìm thông tin gì tại Văn Lang?' : 'Quản lý nguồn', exact: true })).toBeVisible()
    if (denied) await expect(page.getByRole('link', { name: 'Mở trang quản trị' })).toHaveCount(0)
    await page.close()
  }
})

test('permission network and 5xx errors stay on login with retry instead of assuming ordinary user', async ({ browser }) => {
  for (const status of [503, 'network'] as const) {
    const page = await browser.newPage()
    const mock = await fixture(page, { auth: false })
    mock.failPermission(status)
    await page.goto('http://127.0.0.1:5178/login')
    await signIn(page)
    await expect(page.getByRole('heading', { name: 'Chưa thể xác nhận quyền truy cập' })).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)
    expect(mock.requests.some(request => new URL(request.url()).pathname === '/conversations')).toBe(false)
    mock.failPermission(0)
    await page.getByRole('button', { name: 'Thử lại', exact: true }).click()
    await expect(page).toHaveURL(/\/admin\/sources$/)
    await page.close()
  }
})

test('default route resolves role but explicit chat return route is preserved', async ({ browser }) => {
  for (const denied of [0, 403]) {
    const page = await browser.newPage()
    await fixture(page, { denied })
    await page.goto('http://127.0.0.1:5178/')
    await expect(page).toHaveURL(denied ? /\/chat$/ : /\/admin\/sources$/)
    await page.close()
  }
  const page = await browser.newPage()
  await fixture(page, { auth: false })
  await page.goto('http://127.0.0.1:5178/chat')
  await expect(page).toHaveURL(/\/login$/)
  await signIn(page)
  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.getByRole('link', { name: 'Mở trang quản trị' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('link', { name: 'Mở trang quản trị' })).toBeVisible()
  await expect(page).toHaveURL(/\/chat$/)
  await page.close()
})

test('API mock: viewport sidebar, sticky add, pagination and reference screenshots', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await fixture(page, { many: true })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/admin/sources')
  await mkdir(reviewDir, { recursive: true })
  await expect(page.getByRole('heading', { name: file.filename })).toBeVisible()
  await page.screenshot({ path: join(reviewDir, 'sources-desktop.png') })
  await expect(page.getByRole('button', { name: 'Mở điều hướng', exact: true })).toBeHidden()
  const logout = page.getByRole('button', { name: 'Đăng xuất', exact: true })
  const before = await logout.boundingBox()
  await page.locator('#admin-main').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(logout).toBeVisible()
  expect((await logout.boundingBox())!.y).toBe(before!.y)
  await expect(page.getByRole('button', { name: '+ Thêm nguồn', exact: true })).toBeInViewport()
  await page.getByRole('button', { name: 'Trang sau', exact: true }).click()
  await expect(page.getByText('Trang 2', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: file.filename })).toHaveCount(0)
  await page.getByRole('button', { name: 'Trang trước', exact: true }).click()
  await page.locator('#admin-main').evaluate(element => { element.scrollTop = 0 })
  await page.getByRole('button', { name: `Thao tác với ${file.filename}`, exact: true }).click()
  await page.screenshot({ path: join(reviewDir, 'source-menu-desktop.png') })
  await page.keyboard.press('Escape')
  await sourceAction(page, file.filename, 'Sửa thông tin')
  await page.screenshot({ path: join(reviewDir, 'source-edit-desktop.png') })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /^Bộ lọc/ }).click()
  await page.screenshot({ path: join(reviewDir, 'filters-desktop.png') })
  await page.keyboard.press('Escape')
  await openAdd(page)
  await page.screenshot({ path: join(reviewDir, 'add-desktop.png') })
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: join(reviewDir, 'sources-mobile.png') })
  await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
  const nav = page.getByRole('dialog', { name: 'Điều hướng quản trị' })
  await expect(nav.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeInViewport()
  await page.screenshot({ path: join(reviewDir, 'admin-menu-mobile.png') })
  await expect(nav.getByRole('link', { name: 'Thông báo', exact: true })).toHaveCount(0)
  await nav.getByRole('link', { name: 'Quản lý nguồn', exact: true }).click()
  await expect(nav).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Quản lý nguồn', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
  await page.getByRole('dialog').getByRole('link', { name: 'Quản lý nguồn', exact: true }).click()
  await openAdd(page)
  await page.getByRole('dialog').locator('summary').click()
  await page.screenshot({ path: join(reviewDir, 'add-mobile.png') })
  for (const viewport of [{ width: 390, height: 480 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport)
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Thêm nguồn', exact: true })).toBeInViewport()
    const body = page.locator('.admin-dialog-body')
    await body.evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Thêm nguồn', exact: true })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  }
  expect(errors).toEqual([])
})

test('API mock: Chat sidebar and mobile drawer keep account footer visible with long history', async ({ page }) => {
  await fixture(page, { many: true })
  await page.goto('/chat')
  await expect(page.getByRole('complementary', { name: 'Lịch sử trò chuyện', exact: true })).toBeVisible()
  await expect(page.locator('.history-sidebar .conversation-select')).toHaveCount(60)
  expect(await page.locator('.history-sidebar .conversation-list').evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  await expect(page.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeInViewport()
  await page.locator('.history-sidebar .conversation-list').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(page.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeInViewport()
  await page.screenshot({ path: join(reviewDir, 'chat-desktop.png') })
  await page.setViewportSize({ width: 390, height: 640 })
  await page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: 'Lịch sử trò chuyện', exact: true })
  await drawer.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)))
  await expect(drawer.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeInViewport()
  await drawer.locator('.conversation-list').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(drawer.getByRole('button', { name: 'Đăng xuất', exact: true })).toBeInViewport()
  await page.screenshot({ path: join(reviewDir, 'chat-menu-mobile.png') })
  await page.keyboard.press('Escape')
  await expect(drawer).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true })).toBeFocused()
})

test('reference export: render only decoded concept and scoped CSS in light mode without runtime', async ({ page }) => {
  const exported = await readFile('../docs/ui-reference/admin-sources-reference.html', 'utf8')
  const match = exported.match(/data-srcdoc\s*=\s*(["'])([\s\S]*?)\1/)
  expect(match).not.toBeNull()
  const reference = await page.evaluate(value => {
    const decoder = document.createElement('textarea'); decoder.innerHTML = value
    const doc = new DOMParser().parseFromString(decoder.value, 'text/html')
    const concept = doc.querySelector('#vlu-admin-concept')!
    const rows = concept.querySelector('[data-rows]')!
    rows.innerHTML = '<article class="va-source-row"><div class="va-name-cell"><span class="va-type">PDF</span><div class="va-name-content"><button class="va-source-name">Chương trình Marketing.pdf</button><span class="va-source-meta">PDF · 17 đoạn tài liệu</span></div></div><div class="va-status-cell"><span class="va-status">Đang sử dụng</span></div><span class="va-date">30/10/2026</span><button class="va-icon-button va-row-more">⋯</button></article>'
    return { css: Array.from(doc.querySelectorAll('style')).filter(style => style.textContent?.includes('#vlu-admin-concept')).map(style => style.textContent).join('\n'), html: concept.outerHTML }
  }, match![2])
  await page.setContent(`<html style="color-scheme:light"><head><style>body{margin:0}*{box-sizing:border-box}${reference.css}</style></head><body>${reference.html}</body></html>`)
  await mkdir(reviewDir, { recursive: true })
  await page.screenshot({ path: join(reviewDir, 'approved-reference-light.png') })
})
