import { expect, test } from '@playwright/test'
import { join } from 'node:path'
import { mkdir } from 'node:fs/promises'
import { fixture } from './admin-fixtures'

const conversationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const historyId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
const stamp = '2026-11-05T09:00:00Z'
const reviewDir = process.env.ADMIN_REVIEW_DIR ?? '../data/admin-review/chat-progress'
const source = { citation: 1, chunk_id: 'chunk-1', document_id: 'document-1', filename: 'fixture.txt', chunk_index: 0, cosine_distance: .1 }
const answer = 'Câu trả lời đã được kiểm tra [1].'

for (const width of [1440, 390, 320]) {
  test(`Chat sidebar search opens existing history, collapse and toolbar work at ${width}px`, async ({ page }) => {
    const mock = await fixture(page, { denied: 403 })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const loaded: string[] = []
    await page.route('**/conversations', route => route.fulfill({ json: [
      { id: conversationId, title: 'Học phí và học bổng', is_pinned: false, created_at: stamp, updated_at: stamp },
      { id: historyId, title: 'Điều kiện tốt nghiệp', is_pinned: false, created_at: stamp, updated_at: stamp },
    ] }))
    await page.route('**/conversations/*/messages', route => {
      const id = new URL(route.request().url()).pathname.split('/')[2]
      loaded.push(id)
      return route.fulfill({ json: [
        { id: `user-${id}`, conversation_id: id, role: 'user', content: 'Câu hỏi đã lưu', citations: null, created_at: stamp },
        { id: `assistant-${id}`, conversation_id: id, role: 'assistant', content: answer, citations: [source], created_at: stamp },
      ] })
    })
    await page.setViewportSize({ width, height: 844 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/chat')
    const share = page.getByRole('button', { name: 'Chia sẻ cuộc trò chuyện', exact: true })
    await expect(share).toBeDisabled()
    const actions = page.locator('.conversation-toolbar > button')
    for (const button of await actions.all()) {
      const box = (await button.boundingBox())!
      expect(box.height).toBe(44)
      expect(box.width).toBeGreaterThanOrEqual(44)
      await expect(button.locator('svg')).toHaveCSS('width', '22px')
    }
    const search = page.getByRole('button', { name: 'Tìm cuộc trò chuyện', exact: true })
    const drawer = page.getByRole('dialog', { name: 'Lịch sử trò chuyện', exact: true })
    if (width < 901) {
      await page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true }).click()
      await expect(drawer).toBeVisible()
    } else {
      const header = page.locator('.history-sidebar__header')
      const logoBox = (await header.locator('img').boundingBox())!
      const collapse = page.getByRole('button', { name: 'Thu gọn sidebar', exact: true })
      const collapseBox = (await collapse.boundingBox())!
      expect(logoBox.x + logoBox.width).toBeLessThanOrEqual(collapseBox.x)
      const icon = await collapse.locator('svg').innerHTML()
      await collapse.click()
      const expand = page.getByRole('button', { name: 'Mở sidebar', exact: true })
      await expect(expand).toBeInViewport()
      expect(await expand.locator('svg').innerHTML()).toBe(icon)
      await expect(search).toBeInViewport()
      await expand.click()
    }
    const sidebar = width < 901 ? drawer : page.locator('.history-sidebar')
    const headerBox = (await sidebar.locator(width < 901 ? '.history-drawer__header' : '.history-sidebar__header').boundingBox())!
    const create = sidebar.getByRole('button', { name: 'Cuộc trò chuyện mới', exact: true })
    const createBox = (await create.boundingBox())!
    const searchBox = (await search.boundingBox())!
    expect(headerBox.y + headerBox.height).toBeLessThanOrEqual(createBox.y)
    expect(createBox.y + createBox.height).toBeLessThanOrEqual(searchBox.y)
    await expect(create.locator('span')).toHaveText('Cuộc trò chuyện mới')
    await expect(search.locator('span')).toHaveText('Tìm cuộc trò chuyện')
    await mkdir(reviewDir, { recursive: true })
    await page.screenshot({ path: join(reviewDir, `sidebar-order-${width}.png`) })
    await expect(search).toBeInViewport()
    await search.click()
    const dialog = page.getByRole('dialog', { name: 'Tìm cuộc trò chuyện', exact: true })
    const input = dialog.getByRole('searchbox', { name: 'Tìm theo tiêu đề', exact: true })
    await expect(input).toBeFocused()
    await input.fill('không có tiêu đề này')
    await expect(dialog.getByRole('status')).toHaveText('Không tìm thấy cuộc trò chuyện phù hợp.')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(search).toBeFocused()
    if (width < 901) await expect(drawer).toBeVisible()
    await search.click()
    await input.fill('HOC PHI')
    await expect(dialog.getByRole('button', { name: 'Học phí và học bổng', exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Điều kiện tốt nghiệp', exact: true })).toHaveCount(0)
    await mkdir(reviewDir, { recursive: true })
    await page.screenshot({ path: join(reviewDir, `chat-search-${width}.png`) })
    await dialog.getByRole('button', { name: 'Học phí và học bổng', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(drawer).toHaveCount(0)
    await expect(page.locator('.answer-content')).toContainText(answer)
    expect(loaded).toEqual([conversationId])
    await expect(share).toBeEnabled()
    await share.click()
    await expect(page.getByRole('dialog', { name: 'Chia sẻ', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    const menu = page.getByRole('button', { name: 'Mở menu cuộc trò chuyện', exact: true })
    await menu.click()
    await expect(page.getByRole('menuitem', { name: 'Đổi tên đoạn chat', exact: true })).toBeEnabled()
    await page.keyboard.press('Escape')
    await expect(menu).toBeFocused()
    const sources = page.getByRole('button', { name: 'Xem nguồn tham khảo', exact: true })
    await sources.focus()
    await expect(sources).toBeFocused()
    await sources.hover()
    await sources.click()
    await expect(sources).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator('#reference-sources-panel')).toContainText('fixture.txt')
    await page.screenshot({ path: join(reviewDir, `chat-tools-sources-${width}.png`) })
    await page.keyboard.press('Escape')
    await expect(sources).toBeFocused()
    await expect(sources).toHaveAttribute('aria-expanded', 'false')
    if (width < 901) {
      const brand = (await page.locator('.mobile-chat-header__brand').boundingBox())!
      const toolbar = (await page.locator('.conversation-toolbar').boundingBox())!
      expect(brand.x + brand.width).toBeLessThanOrEqual(toolbar.x)
      expect(toolbar.x + toolbar.width).toBeLessThanOrEqual(width)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: join(reviewDir, `chat-tools-${width}.png`) })
    if (width < 901) await page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true }).click()
    await create.click()
    await expect(drawer).toHaveCount(0)
    await expect(page.locator('.answer-content')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })).toHaveValue('')
    expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/questions'))).toBe(false)
    expect(errors).toEqual([])
  })
}

test('Collapsed sidebar swaps the VLU mark on hover and Tab; blank area and controls act independently', async ({ page }) => {
  const mock = await fixture(page, { denied: 403 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/chat')
  const sidebar = page.locator('.history-sidebar')
  const collapse = page.getByRole('button', { name: 'Thu gọn sidebar', exact: true })
  const expand = page.getByRole('button', { name: 'Mở sidebar', exact: true })
  const create = sidebar.getByRole('button', { name: 'Cuộc trò chuyện mới', exact: true })
  const search = sidebar.getByRole('button', { name: 'Tìm cuộc trò chuyện', exact: true })
  const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
  await input.fill('Câu nháp trước khi tạo chat')
  await collapse.click()
  await input.focus()
  await page.mouse.move(500, 400)
  const mark = expand.locator('.history-sidebar__brand-mark')
  const icon = expand.locator('.history-sidebar__toggle-icon')
  await expect(mark).toHaveCSS('opacity', '1')
  await expect(icon).toHaveCSS('opacity', '0')
  const slot = (await expand.boundingBox())!
  const newBox = (await create.boundingBox())!
  const searchBox = (await search.boundingBox())!
  expect(slot.y + slot.height).toBeLessThanOrEqual(newBox.y)
  expect(newBox.y + newBox.height).toBeLessThanOrEqual(searchBox.y)
  await expect(create.locator('span')).toHaveCount(0)
  await expect(search.locator('span')).toHaveCount(0)
  await mkdir(reviewDir, { recursive: true })
  await page.screenshot({ path: join(reviewDir, 'sidebar-collapsed-default.png') })
  await expand.hover()
  await expect(mark).toHaveCSS('opacity', '0')
  await expect(icon).toHaveCSS('opacity', '1')
  expect(await expand.boundingBox()).toEqual(slot)
  await page.screenshot({ path: join(reviewDir, 'sidebar-collapsed-hover.png') })
  await page.mouse.move(500, 400)
  await create.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(expand).toBeFocused()
  await expect(mark).toHaveCSS('opacity', '0')
  await expect(icon).toHaveCSS('opacity', '1')
  expect(await expand.boundingBox()).toEqual(slot)
  await page.keyboard.press('Space')
  await expect(collapse).toBeVisible()
  await collapse.focus()
  await page.keyboard.press('Enter')
  await expect(expand).toBeVisible()
  await sidebar.click({ position: { x: 32, y: 400 } })
  await expect(collapse).toBeVisible()
  await collapse.click()
  await create.locator('svg').click()
  await expect(input).toHaveValue('')
  await expect(expand).toBeVisible()
  await search.locator('svg circle').click()
  const dialog = page.getByRole('dialog', { name: 'Tìm cuộc trò chuyện', exact: true })
  await expect(dialog).toBeVisible()
  await expect(sidebar).toHaveClass(/history-sidebar--collapsed/)
  await page.keyboard.press('Escape')
  await expect(search).toBeFocused()
  let release!: () => void
  const holdLogout = new Promise<void>(resolve => { release = resolve })
  await page.route('**/auth/v1/logout*', async route => { await holdLogout; await route.fulfill({ status: 204 }) })
  await sidebar.getByRole('button', { name: 'Đăng xuất', exact: true }).locator('svg').click()
  await expect(sidebar.getByRole('button', { name: 'Đang đăng xuất', exact: true })).toBeDisabled()
  await expect(sidebar).toHaveClass(/history-sidebar--collapsed/)
  release()
  await expect(page).toHaveURL(/\/$/)
  expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/questions'))).toBe(false)
})

test('Collapsed VLU logo opens the sidebar with a touch tap without hovering', async ({ browser }) => {
  const page = await browser.newPage({ hasTouch: true, viewport: { width: 1440, height: 900 } })
  await fixture(page, { denied: 403 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('http://127.0.0.1:5178/chat')
  await page.getByRole('button', { name: 'Thu gọn sidebar', exact: true }).tap()
  const expand = page.getByRole('button', { name: 'Mở sidebar', exact: true })
  await expect(expand.locator('.history-sidebar__brand-mark')).toHaveCSS('opacity', '1')
  await expand.tap()
  await expect(page.getByRole('button', { name: 'Thu gọn sidebar', exact: true })).toBeVisible()
  await page.close()
})
