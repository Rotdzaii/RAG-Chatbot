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
  const action = page.getByRole('menu', { name: `Thao tác với ${filename}`, exact: true }).getByRole('menuitem', { name: label, exact: true })
  await expect(action).toHaveAttribute('title', label)
  await action.click()
}

async function openAdd(page: Page, kind = 'file') {
  await page.getByRole('button', { name: '+ Thêm tài liệu', exact: true }).click()
  await page.getByRole('tab', { name: kind === 'url' ? 'Nhập URL' : 'Tải tệp lên', exact: true }).click()
  return page.getByRole('dialog')
}

async function filter(page: Page, values: { type?: string; active?: string; category?: string; audience?: string }) {
  await page.getByRole('button', { name: /^Bộ lọc/ }).click()
  const dialog = page.getByRole('dialog')
  if (values.type !== undefined) await dialog.getByLabel('Loại tài liệu', { exact: true }).selectOption(values.type)
  if (values.active !== undefined) await dialog.getByLabel('Trạng thái sử dụng', { exact: true }).selectOption(values.active)
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
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Thông báo', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '+ Thêm tài liệu', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
  const navigation = page.getByRole('dialog', { name: 'Điều hướng quản trị' })
  await expect(navigation.getByRole('link', { name: 'Thông báo', exact: true })).toHaveCount(0)
  await navigation.getByRole('link', { name: 'Quản lý tài liệu', exact: true }).click()
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
  await page.getByRole('button', { name: 'Bỏ lọc Loại tài liệu' }).click()
  await expect(page.getByRole('heading', { name: urlSource.filename })).toBeVisible()
  await filter(page, { category: 'missing', audience: 'staff' })
  await expect(page.getByRole('heading', { name: 'Chưa có tài liệu trong danh sách này' })).toBeVisible()
  await page.getByRole('button', { name: /^Bộ lọc/ }).click()
  await page.getByRole('button', { name: 'Xóa bộ lọc', exact: true }).click()
  await expect(page.getByRole('heading', { name: file.filename })).toBeVisible()
  const more = page.getByRole('button', { name: `Thao tác với ${file.filename}` })
  await more.focus(); await page.keyboard.press('ArrowDown')
  const items = page.getByRole('menu').getByRole('menuitem')
  await expect(items.first()).toBeFocused()
  await page.keyboard.press('End'); await expect(items.last()).toBeFocused()
  await expect(items.last()).toHaveText('Xóa tài liệu')
  await page.keyboard.press('Escape'); await expect(more).toBeFocused()
})

test('downloads the stored PDF with its current filename and reports missing originals', async ({ page }) => {
  await fixture(page)
  const filename = 'Chương trình Marketing mới.pdf'
  const bytes = Buffer.from('%PDF-original fixture bytes')
  let available = true
  await page.route(`**/admin/knowledge-sources/${file.id}/file`, route => {
    expect(route.request().method()).toBe('GET')
    expect(route.request().headers().authorization).toMatch(/^Bearer /)
    return available ? route.fulfill({
      contentType: 'application/pdf',
      headers: {
        'Content-Disposition': `attachment; filename="source.pdf"; filename*=UTF-8''${encodeURIComponent(filename)}`,
        'Access-Control-Expose-Headers': 'Content-Disposition',
      },
      body: bytes,
    }) : route.fulfill({ status: 404, json: { detail: 'Source file not found' } })
  })
  await page.goto('/admin/sources')

  const ready = page.waitForEvent('download')
  await sourceAction(page, file.filename, 'Tải tệp gốc')
  const download = await ready
  expect(download.suggestedFilename()).toBe(filename)
  expect(await readFile((await download.path())!)).toEqual(bytes)

  available = false
  await sourceAction(page, file.filename, 'Tải tệp gốc')
  await expect(page.getByRole('alert')).toContainText('Không tìm thấy tệp gốc cho tài liệu này.')
})

for (const width of [1440, 390]) {
  test(`filename search reaches later pages, resets pagination and combines filters at ${width}px`, async ({ page }) => {
    const mock = await fixture(page, { many: true })
    await page.setViewportSize({ width, height: 844 })
    await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' })
    await page.goto('/admin/sources')
    const target = 'Tài liệu kiểm thử 47.pdf'
    await expect(page.getByRole('heading', { name: target, exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Trang sau', exact: true }).click()
    await expect(page.getByText('Trang 2', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Trang sau', exact: true }).click()
    await expect(page.getByRole('heading', { name: target, exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Trang trước', exact: true }).click()
    await expect(page.getByText('Trang 2', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: target, exact: true })).toHaveCount(0)
    const search = page.getByRole('searchbox', { name: 'Tìm theo tên file', exact: true })
    const clear = page.getByRole('button', { name: 'Xóa từ khóa tìm kiếm', exact: true })
    await search.fill('  KIỂM THỬ 47  ')
    await expect(page.getByText('Trang 1', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: target, exact: true })).toBeVisible()
    await expect(page.getByText('Hiển thị 1 / 1 tài liệu', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Trang sau', exact: true })).toBeDisabled()
    const request = mock.requests.filter(request => new URL(request.url()).searchParams.has('filename')).at(-1)!
    expect(new URL(request.url()).searchParams.get('filename')).toBe('KIỂM THỬ 47')
    expect(new URL(request.url()).searchParams.get('offset')).toBe('0')
    await search.fill('KIỂM THỬ')
    await expect(page.getByText('Hiển thị 20 / 48 tài liệu', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Trang sau', exact: true }).click()
    await expect(page.getByText('Trang 2', { exact: true })).toBeVisible()
    await clear.click()
    await expect(page.getByText('Trang 1', { exact: true })).toBeVisible()
    await expect(page.getByText('Hiển thị 20 / 50 tài liệu', { exact: true })).toBeVisible()
    await expect(search).toBeFocused()
    await search.fill('  KIỂM THỬ 47  ')
    await expect(page.getByRole('heading', { name: target, exact: true })).toBeVisible()
    await sourceAction(page, target, 'Sửa thông tin')
    const metadata = page.getByRole('dialog')
    await metadata.getByLabel('Phân loại', { exact: true }).fill('curriculum')
    await metadata.getByLabel('Đối tượng', { exact: true }).fill('students')
    await metadata.getByRole('button', { name: 'Lưu thông tin', exact: true }).click()
    await expect(metadata).toHaveCount(0)
    await filter(page, { type: 'file', active: 'true', category: 'curriculum', audience: 'students' })
    await expect(page.getByRole('heading', { name: target, exact: true })).toBeVisible()
    const combined = new URL(mock.requests.filter(request => new URL(request.url()).searchParams.get('audience') === 'students').at(-1)!.url())
    expect(Object.fromEntries(combined.searchParams)).toMatchObject({ filename: 'KIỂM THỬ 47', source_type: 'file', is_active: 'true', category: 'curriculum', audience: 'students', offset: '0' })
    await search.fill('không tìm thấy tên file')
    await expect(page.getByRole('heading', { name: 'Chưa có tài liệu trong danh sách này', exact: true })).toBeVisible()
    await expect(page.getByText('Hiển thị 0 / 0 tài liệu', { exact: true })).toBeVisible()
    await clear.click()
    await expect(search).toHaveValue('')
    await expect(search).toBeFocused()
    await expect(page.getByRole('heading', { name: target, exact: true })).toBeVisible()
    await expect(page.getByLabel('Điều kiện đang áp dụng')).toContainText('curriculum')
    await expect(clear).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await mkdir(reviewDir, { recursive: true })
    await page.screenshot({ path: join(reviewDir, `source-search-${width}.png`) })
    const add = await openAdd(page)
    await expect(add.getByText('Gợi ý đặt tên: ky-thuat-phan-mem_k32_chuong-trinh-dao-tao.pdf (không bắt buộc).', { exact: true })).toBeVisible()
    await page.screenshot({ path: join(reviewDir, `source-upload-naming-${width}.png`) })
    await add.getByLabel('Chọn tài liệu', { exact: true }).setInputFiles({ name: 'ten-khac.txt', mimeType: 'text/plain', buffer: Buffer.from('mock upload') })
    await add.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
    await expect(add).toHaveCount(0)
    expect(mock.requests.filter(request => new URL(request.url()).pathname === '/documents').at(-1)!.postDataBuffer()?.toString()).toContain('filename="ten-khac.txt"')
  })
}

for (const kind of ['pdf', 'txt', 'url']) {
  test(`API mock: ${kind} upload validation pending error retry optional fields and list update`, async ({ page }) => {
    const mock = await fixture(page, { empty: true })
    await page.goto('/admin/sources')
    const dialog = await openAdd(page, kind)
    if (kind === 'url') await dialog.getByLabel('Địa chỉ liên kết').fill('https://www.vlu.edu.vn/new-source')
    else {
      await dialog.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
      await expect(dialog.getByRole('alert')).toContainText('Hãy chọn tài liệu')
      await dialog.getByLabel('Chọn tài liệu', { exact: true }).setInputFiles({ name: `new.${kind}`, mimeType: kind === 'pdf' ? 'application/pdf' : 'text/plain', buffer: Buffer.from('isolated fixture') })
    }
    await dialog.locator('summary').click()
    await dialog.getByLabel('Phân loại', { exact: true }).fill('policy')
    await dialog.getByLabel('Đối tượng', { exact: true }).fill('staff')
    mock.failMutations(503)
    let release!: () => void
    mock.hold(new Promise<void>(resolve => { release = resolve }))
    await dialog.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText('Đang xử lý tài liệu')
    await expect(dialog.getByRole('button', { name: 'Đang xử lý…', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('button', { name: 'Đóng hộp thoại' })).toBeDisabled()
    release(); await expect(dialog.getByRole('alert')).toContainText('Dịch vụ tạm thời chưa sẵn sàng.')
    mock.hold(); mock.failMutations(0)
    await dialog.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
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
    await sourceAction(page, source.filename, 'Tạm ngưng sử dụng')
    await expect(page.getByRole('dialog').getByRole('heading', { name: 'Tạm ngưng sử dụng tài liệu?', exact: true })).toBeVisible()
    await expect(page.getByRole('dialog')).toContainText('câu trả lời đã lưu không tự được sửa')
    expect(mock.requests.filter(request => request.url().endsWith('/status'))).toHaveLength(source === file ? 0 : 1)
    await page.getByRole('dialog').getByRole('button', { name: 'Tạm ngưng sử dụng', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: 'Đã tạm ngưng sử dụng tài liệu.' })).toHaveText('Đã tạm ngưng sử dụng tài liệu.')
  }
  await expect(page.locator('.admin-source-status--inactive')).toHaveCount(2)
  await expect(page.locator('.admin-source-status--inactive')).toHaveText(['Tạm ngưng', 'Tạm ngưng'])
  let filename = file.filename
  for (const kind of ['pdf', 'txt']) {
    await sourceAction(page, filename, 'Thay file')
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Cập nhật giữ nguyên trạng thái tạm ngưng')
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
  await sourceAction(page, urlSource.filename, 'Cập nhật từ liên kết')
  mock.failMutations(502)
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật từ liên kết', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Không tải được tài liệu từ liên kết.')
  mock.failMutations(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật từ liên kết', exact: true }).click()
  await expect(page.getByText('Nội dung từ liên kết không thay đổi.', { exact: true })).toBeVisible()
  mock.refreshStatus('updated')
  await sourceAction(page, urlSource.filename, 'Cập nhật từ liên kết')
  await page.getByRole('dialog').getByRole('button', { name: 'Cập nhật từ liên kết', exact: true }).click()
  await expect(page.getByText('Đã cập nhật tài liệu từ liên kết.', { exact: true })).toBeVisible()
  await filter(page, { active: 'false' })
  await sourceAction(page, filename, 'Cho phép sử dụng')
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Cho phép sử dụng tài liệu?', exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Cho phép sử dụng', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Đã cho phép sử dụng tài liệu.' })).toHaveText('Đã cho phép sử dụng tài liệu.')
  await expect(page.getByRole('heading', { name: filename, exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Bỏ lọc Trạng thái sử dụng' }).click()
  await expect(page.locator('.admin-source-status--active')).toHaveCount(1)
  await expect(page.locator('.admin-source-status--active')).toHaveText('Đang sử dụng')
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
  await expect(page.getByRole('heading', { name: 'Chưa có tài liệu trong danh sách này' })).toBeVisible()
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
  await sourceAction(page, urlSource.filename, 'Mở trang gốc')
  expect(JSON.parse(await page.evaluate(() => document.documentElement.dataset.openedSource!))).toEqual({ url: urlSource.source_url, target: '_blank', features: 'noopener,noreferrer' })
  expect(mock.requests.some(request => request.url().endsWith('/original'))).toBe(false)
  await sourceAction(page, file.filename, 'Xóa tài liệu')
  await expect(page.getByRole('button', { name: 'Giữ lại' })).toBeFocused()
  await page.keyboard.press('Escape')
  expect(mock.requests.filter(request => request.method() === 'DELETE')).toHaveLength(0)
  await sourceAction(page, file.filename, 'Xóa tài liệu')
  mock.failMutations(503)
  await page.getByRole('dialog').getByRole('button', { name: 'Xóa tài liệu', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
  mock.failMutations(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Xóa tài liệu', exact: true }).click()
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
    await dialog.getByLabel('Địa chỉ liên kết').fill('https://example.com/test')
    await dialog.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Dùng URL HTTPS thuộc')
    await dialog.getByLabel('Địa chỉ liên kết').fill('https://www.vlu.edu.vn/new-source')
    mock.failMutations(status)
    await dialog.getByRole('button', { name: 'Thêm tài liệu', exact: true }).click()
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
      await expect(page.getByRole('button', { name: 'Thêm tài liệu' })).toHaveCount(0)
    }
    if (denied === 401) {
      await expect(page.getByRole('heading', { name: 'Phiên đăng nhập đã hết hạn' })).toBeVisible()
      await page.getByRole('button', { name: 'Đăng nhập lại' }).click()
      await expect(page).toHaveURL(/\/login$/)
    }
    await page.close()
  }
})

test('admin opening chat is redirected before chat or history mount, including after token refresh', async ({ page }) => {
  const mock = await fixture(page)
  let release!: () => void
  mock.holdPermission(new Promise<void>(resolve => { release = resolve }))
  await page.goto('/chat')
  await expect(page.getByText('Đang xác nhận quyền truy cập…', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Câu hỏi của bạn' })).toHaveCount(0)
  expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/conversations'))).toBe(false)
  release()
  await expect(page).toHaveURL(/\/admin$/)
  await mock.refreshSession()
  await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
  await page.goto('/chat')
  await expect(page).toHaveURL(/\/admin$/)
  expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/conversations') || new URL(request.url()).pathname.startsWith('/questions'))).toBe(false)
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
    await expect(page).toHaveURL(/\/$/)
    expect(await page.evaluate(() => localStorage.getItem('sb-127-auth-token'))).toBeNull()
    await page.goto('http://127.0.0.1:5178/admin')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toHaveCount(0)
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
    await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toHaveCount(0)
    expect(mock.requests.filter(request => new URL(request.url()).pathname === '/conversations')).toHaveLength(0)
    release()
    await expect(page).toHaveURL(denied ? /\/chat$/ : /\/admin$/)
    await expect(page.getByRole('heading', { name: denied ? 'Bạn cần tìm thông tin gì tại Văn Lang?' : 'Tổng quan', exact: true })).toBeVisible()
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
    await expect(page).toHaveURL(/\/admin$/)
    await page.close()
  }
})

test('default route resolves role and admin login overrides an explicit chat return route', async ({ browser }) => {
  for (const denied of [0, 403]) {
    const page = await browser.newPage()
    await fixture(page, { denied })
    await page.goto('http://127.0.0.1:5178/')
    await expect(page).toHaveURL(denied ? /\/chat$/ : /\/admin$/)
    await page.close()
  }
  const page = await browser.newPage()
  await fixture(page, { auth: false })
  await page.goto('http://127.0.0.1:5178/chat')
  await expect(page).toHaveURL(/\/login$/)
  await signIn(page)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/admin$/)
  await page.close()
})

for (const width of [1440, 390]) {
  test(`Home draft login routes Admin to the overview, hides chat links and logout clears draft at ${width}px`, async ({ page }) => {
    const mock = await fixture(page, { auth: false })
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/')
    await page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true }).fill('Câu nháp trước khi đăng nhập Admin')
    await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
    await page.getByRole('button', { name: 'Tiếp tục bằng email', exact: true }).click()
    await signIn(page)
    await expect(page).toHaveURL(/\/admin$/)
    await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Về trò chuyện', exact: true })).toHaveCount(0)
    if (width === 390) {
      await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
      await expect(page.getByRole('dialog').getByRole('link', { name: 'Về trò chuyện', exact: true })).toHaveCount(0)
    }
    await page.getByRole('button', { name: 'Đăng xuất', exact: true }).filter({ visible: true }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })).toHaveValue('')
    expect(await page.evaluate(() => sessionStorage.getItem('vlu.pending-chat-question'))).toBeNull()
    await page.reload()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })).toHaveValue('')
    expect(mock.requests.some(request => /^\/(conversations|questions)(\/|$)/.test(new URL(request.url()).pathname))).toBe(false)
  })
}

for (const width of [1440, 390]) {
  test(`Google callback routes Admin by backend permission before mounting chat at ${width}px`, async ({ page }) => {
    const mock = await fixture(page, { auth: false })
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/')
    await page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true }).fill('Câu nháp Google của Admin')
    await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
    expect(mock.oauthRequests).toHaveLength(0)
    await page.getByRole('button', { name: 'Tiếp tục bằng Google', exact: true }).click()
    await expect(page).toHaveURL(/\/admin$/)
    await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
    await expect(page.getByRole('dialog', { name: 'Đăng nhập hoặc đăng ký', exact: true })).toHaveCount(0)
    expect(mock.oauthRequests).toHaveLength(1)
    expect(mock.requests.some(request => /^\/(questions|conversations)(\/|$)/.test(new URL(request.url()).pathname))).toBe(false)
  })

  test(`authenticated User and Admin never see the Home login prompt at ${width}px`, async ({ browser }) => {
    for (const denied of [0, 403]) {
      const page = await browser.newPage({ viewport: { width, height: 844 } })
      const mock = await fixture(page, { denied })
      await page.goto('http://127.0.0.1:5178/')
      await expect(page).toHaveURL(denied ? /\/chat$/ : /\/admin$/)
      await expect(page.getByRole('heading', { name: denied ? 'Bạn cần tìm thông tin gì tại Văn Lang?' : 'Tổng quan', exact: true })).toBeVisible()
      await expect(page.getByRole('dialog', { name: 'Đăng nhập hoặc đăng ký', exact: true })).toHaveCount(0)
      expect(mock.oauthRequests).toHaveLength(0)
      await page.close()
    }
  })
}

for (const failure of [503, 'network', 401] as const) {
  test(`direct chat blocks mount on permission ${failure} and can recover`, async ({ page }) => {
    const mock = await fixture(page)
    mock.failPermission(failure)
    await page.goto('/chat')
    await expect(page.getByRole('heading', { name: failure === 401 ? 'Phiên đăng nhập đã hết hạn' : 'Chưa thể xác nhận quyền truy cập' })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })).toHaveCount(0)
    expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/conversations'))).toBe(false)
    mock.failPermission(0)
    if (failure === 401) {
      await page.getByRole('button', { name: 'Đăng nhập lại', exact: true }).click()
      await expect(page).toHaveURL(/\/login$/)
      await signIn(page)
    } else await page.getByRole('button', { name: 'Thử lại', exact: true }).click()
    await expect(page).toHaveURL(/\/admin$/)
    expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/conversations'))).toBe(false)
  })
}

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
  await expect(page.getByRole('button', { name: '+ Thêm tài liệu', exact: true })).toBeInViewport()
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
  await nav.getByRole('link', { name: 'Quản lý tài liệu', exact: true }).click()
  await expect(nav).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Mở điều hướng', exact: true }).click()
  await page.getByRole('dialog').getByRole('link', { name: 'Quản lý tài liệu', exact: true }).click()
  await openAdd(page)
  await page.getByRole('dialog').locator('summary').click()
  await page.screenshot({ path: join(reviewDir, 'add-mobile.png') })
  for (const viewport of [{ width: 390, height: 480 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport)
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Thêm tài liệu', exact: true })).toBeInViewport()
    const body = page.locator('.admin-dialog-body')
    await body.evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Thêm tài liệu', exact: true })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  }
  await page.keyboard.press('Escape')
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await page.getByRole('button', { name: `Thao tác với ${urlSource.filename}`, exact: true }).click()
    const menu = page.getByRole('menu', { name: `Thao tác với ${urlSource.filename}`, exact: true })
    await expect(menu.getByRole('menuitem', { name: 'Mở trang gốc', exact: true })).toHaveAttribute('title', 'Mở trang gốc')
    await expect(menu.getByRole('menuitem', { name: 'Cập nhật từ liên kết', exact: true })).toBeVisible()
    expect(await menu.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
    const menuBox = (await menu.boundingBox())!
    expect(menuBox.x).toBeGreaterThanOrEqual(0)
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: join(reviewDir, `document-menu-${width}.png`) })
    await page.keyboard.press('Escape')
    for (const [name, action] of [[urlSource.filename, 'Cập nhật từ liên kết'], [file.filename, 'Tạm ngưng sử dụng']]) {
      await sourceAction(page, name, action)
      const dialog = page.getByRole('dialog')
      await expect(dialog.getByRole('button', { name: action, exact: true })).toBeInViewport()
      expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await dialog.locator('.admin-dialog__actions button').evaluateAll(buttons => buttons.every(button => button.scrollWidth <= button.clientWidth))).toBe(true)
      await page.screenshot({ path: join(reviewDir, `document-${action.startsWith('Cập nhật') ? 'refresh' : 'pause'}-${width}.png`) })
      await page.keyboard.press('Escape')
    }
    await page.getByRole('button', { name: /^Bộ lọc/ }).click()
    const filterDialog = page.getByRole('dialog')
    await expect(filterDialog.getByLabel('Loại tài liệu', { exact: true })).toBeVisible()
    await expect(filterDialog.getByLabel('Trạng thái sử dụng', { exact: true })).toBeVisible()
    expect(await filterDialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
    await page.screenshot({ path: join(reviewDir, `document-filters-${width}.png`) })
    await page.keyboard.press('Escape')
  }
  expect(errors).toEqual([])
})

test('API mock: Chat sidebar and mobile drawer keep account footer visible with long history', async ({ page }) => {
  await fixture(page, { many: true, denied: 403 })
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
