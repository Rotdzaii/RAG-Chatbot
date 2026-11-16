import { expect, test } from '@playwright/test'
import { join } from 'node:path'
import { mkdir } from 'node:fs/promises'
import { fixture, signIn } from './admin-fixtures'

const conversationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const stamp = '2026-11-05T09:00:00Z'
const reviewDir = process.env.ADMIN_REVIEW_DIR ?? '../data/admin-review/chat-progress'
const source = { citation: 1, chunk_id: 'chunk-1', document_id: 'document-1', filename: 'fixture.txt', chunk_index: 0, cosine_distance: .1 }
const answer = 'Câu trả lời đã được kiểm tra [1].'

for (const width of [1440, 390]) {
  for (const mode of ['typed', 'suggested']) {
    test(`guest ${mode} draft survives User login without sending and logout returns Home at ${width}px`, async ({ page }) => {
      const mock = await fixture(page, { auth: false, denied: 403 })
      const questions: string[] = []
      page.on('request', request => {
        if (/\/questions(?:\/stream)?$/.test(new URL(request.url()).pathname)) questions.push(request.postData() ?? '')
      })
      await page.route('**/questions/stream', route => route.fulfill({
        contentType: 'text/event-stream',
        body: `event: result\ndata: ${JSON.stringify({ request_id: route.request().postDataJSON().request_id, response: { answer, sources: [source], conversation_id: conversationId } })}\n\n`,
      }))
      await page.setViewportSize({ width, height: 844 })
      await page.goto('/')
      const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
      await expect(page.getByRole('heading', { name: 'Bạn cần tìm thông tin gì tại Văn Lang?' })).toBeVisible()
      await expect(page.getByRole('complementary', { name: 'Lịch sử trò chuyện', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true })).toHaveCount(0)
      const draft = mode === 'typed' ? 'Tôi muốn hỏi về chương trình đào tạo.\nĐiều kiện tốt nghiệp là gì?' : 'Điều kiện xét tốt nghiệp gồm những gì?'
      if (mode === 'typed') await input.fill(draft)
      else {
        await page.getByRole('button', { name: draft, exact: true }).click()
        await expect(input).toBeFocused()
      }
      await expect(input).toHaveValue(draft)
      await expect(page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true })).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(mock.requests).toHaveLength(0)
      expect(questions).toHaveLength(0)
      await mkdir(reviewDir, { recursive: true })
      await page.screenshot({ path: join(reviewDir, `home-${mode}-${width}.png`) })
      await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
      await page.getByRole('button', { name: 'Tiếp tục bằng email', exact: true }).click()
      await expect(page).toHaveURL(/\/login$/)
      // Reloading login must retain the sessionStorage handoff.
      await page.reload()
      await signIn(page)
      await expect(page).toHaveURL(/\/chat$/)
      await expect(input).toHaveValue(draft)
      await expect(page.getByRole('button', { name: 'Gửi câu hỏi', exact: true })).toBeEnabled()
      await expect.poll(() => mock.requests.some(request => new URL(request.url()).pathname === '/conversations')).toBe(true)
      await expect(page.locator('.chat-turn')).toHaveCount(0)
      expect(questions).toHaveLength(0)
      expect(await page.evaluate(() => sessionStorage.getItem('vlu.pending-chat-question'))).toBeNull()
      await page.route('**/conversations', route => route.fulfill({ json: [
        { id: conversationId, title: 'Hội thoại kiểm thử', is_pinned: false, created_at: stamp, updated_at: stamp },
      ] }))
      await page.getByRole('button', { name: 'Gửi câu hỏi', exact: true }).click()
      await expect(page.locator('.answer-content')).toContainText(answer)
      expect(questions).toHaveLength(1)
      expect(JSON.parse(questions[0]).question).toBe(draft)
      await input.fill('Câu nháp của phiên User cũ')
      await page.evaluate(() => sessionStorage.setItem('vlu.pending-chat-question', 'Câu nháp cũ chưa dùng'))
      if (width === 390) await page.getByRole('button', { name: 'Mở lịch sử trò chuyện', exact: true }).click()
      await page.getByRole('button', { name: 'Đăng xuất', exact: true }).filter({ visible: true }).click()
      await expect(page).toHaveURL(/\/$/)
      await expect(input).toHaveValue('')
      expect(await page.evaluate(() => sessionStorage.getItem('vlu.pending-chat-question'))).toBeNull()
      await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click()
      await page.getByRole('button', { name: 'Tiếp tục bằng email', exact: true }).click()
      await signIn(page)
      await expect(page).toHaveURL(/\/chat$/)
      await expect(input).toHaveValue('')
      expect(questions).toHaveLength(1)
    })
  }
}

for (const reducedMotion of ['reduce', 'no-preference'] as const) {
  test(`Home reveal respects ${reducedMotion}, stays static while editing and cleans up on exit`, async ({ page }) => {
    await fixture(page, { auth: false })
    await page.addInitScript(() => {
      sessionStorage.setItem('vlu.home-login-prompt-seen', 'true')
      new MutationObserver(records => {
        if (records.some(record => (record.target as Element).matches('.home-page .welcome') && /opacity:\s*0(?:;|$)/.test(record.oldValue ?? ''))) {
          document.documentElement.dataset.homeEntranceSeen = 'true'
        }
      }).observe(document, { subtree: true, attributes: true, attributeOldValue: true, attributeFilter: ['style'] })
    })
    await page.emulateMedia({ reducedMotion })
    await page.setViewportSize({ width: 320, height: 568 })
    await page.goto('/')
    const welcome = page.locator('.home-page .welcome')
    const suggestions = page.locator('.home-page .suggested-questions')
    await expect(welcome).toHaveCSS('opacity', '1')
    await expect(welcome).toHaveCSS('transform', 'none')
    await expect(suggestions).toHaveCSS('transform', 'none')
    expect(await page.evaluate(() => document.documentElement.dataset.homeEntranceSeen)).toBe(reducedMotion === 'reduce' ? undefined : 'true')
    await page.evaluate(() => {
      document.documentElement.dataset.homeMotionChanges = '0'
      new MutationObserver(records => {
        for (const record of records) {
          if ((record.target as Element).matches('.home-page .welcome, .home-page .suggested-questions')) {
            const style = getComputedStyle(record.target as Element)
            // matchMedia cleanup may rewrite an already static inline style.
            if (style.opacity !== '1' || style.transform !== 'none') {
              document.documentElement.dataset.homeMotionChanges = String(Number(document.documentElement.dataset.homeMotionChanges) + 1)
            }
          }
        }
      }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['style'] })
    })
    await page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true }).fill('Câu hỏi đang soạn')
    await page.getByRole('button', { name: 'Điều kiện xét tốt nghiệp gồm những gì?', exact: true }).click()
    await page.emulateMedia({ reducedMotion: reducedMotion === 'reduce' ? 'no-preference' : 'reduce' })
    await expect(welcome).toHaveCSS('transform', 'none')
    expect(await page.evaluate(() => document.documentElement.dataset.homeMotionChanges)).toBe('0')
    await expect(page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
    await page.getByRole('button', { name: 'Tiếp tục bằng email', exact: true }).click()
    await expect(page).toHaveURL(/\/login$/)
    await expect(welcome).toHaveCount(0)
  })
}

for (const width of [1440, 390]) {
  test(`Home login dialog waits 750ms, opens once per tab and restores focus at ${width}px`, async ({ page }) => {
    const mock = await fixture(page, { auth: false })
    await page.setViewportSize({ width, height: 844 })
    await page.clock.install({ time: new Date('2026-11-16T08:59:00Z') })
    await page.clock.pauseAt(new Date('2026-11-16T09:00:00Z'))
    await page.goto('/')
    const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
    await input.focus()
    const dialog = page.getByRole('dialog', { name: 'Đăng nhập hoặc đăng ký', exact: true })
    await page.clock.runFor(749)
    await expect(dialog).toHaveCount(0)
    await page.clock.runFor(1)
    await expect(dialog).toBeVisible()
    // Allow the final animation frame to run before pausing the fake clock again.
    await page.clock.runFor(300)
    await expect(dialog).toHaveCSS('opacity', '1')
    await expect(dialog).toBeInViewport()
    const close = dialog.getByRole('button', { name: 'Đóng hộp đăng nhập', exact: true })
    await expect(close).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(dialog.getByRole('button', { name: 'Tiếp tục bằng email', exact: true })).toBeFocused()
    expect(mock.oauthRequests).toHaveLength(0)
    expect(mock.requests).toHaveLength(0)
    await mkdir(reviewDir, { recursive: true })
    await page.screenshot({ path: join(reviewDir, `home-login-dialog-${width}.png`) })
    if (width === 390) await close.click()
    else await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(input).toBeFocused()
    await page.clock.runFor(5000)
    await expect(dialog).toHaveCount(0)
    await page.reload()
    await page.clock.runFor(5000)
    await expect(dialog).toHaveCount(0)
    const login = page.getByRole('button', { name: 'Đăng nhập', exact: true })
    await login.click()
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(login).toBeFocused()
    expect(mock.oauthRequests).toHaveLength(0)
  })

  for (const mode of ['typing', 'suggestion']) {
    test(`Home ${mode} cancels the auto prompt and manual dialog preserves draft at ${width}px`, async ({ page }) => {
      await fixture(page, { auth: false })
      await page.setViewportSize({ width, height: 844 })
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.clock.install({ time: new Date('2026-11-16T08:59:00Z') })
      await page.clock.pauseAt(new Date('2026-11-16T09:00:00Z'))
      await page.goto('/')
      const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
      const draft = mode === 'typing' ? 'Câu hỏi đang soạn' : 'Điều kiện xét tốt nghiệp gồm những gì?'
      if (mode === 'typing') await input.fill(draft)
      else await page.getByRole('button', { name: draft, exact: true }).click()
      await page.clock.runFor(1000)
      const dialog = page.getByRole('dialog', { name: 'Đăng nhập hoặc đăng ký', exact: true })
      await expect(dialog).toHaveCount(0)
      await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
      await expect(dialog).toBeVisible()
      await expect(dialog).toHaveCSS('transform', 'none')
      await expect(dialog).toHaveCSS('opacity', '1')
      await page.keyboard.press('Escape')
      await expect(input).toHaveValue(draft)
      await page.clock.runFor(5000)
      await expect(dialog).toHaveCount(0)
      await input.fill('')
      await page.clock.runFor(1000)
      await expect(dialog).toHaveCount(0)
    })
  }

  for (const outcome of ['cancel', 'error'] as const) {
    test(`Google ${outcome} callback keeps draft and retries into User chat at ${width}px`, async ({ page }) => {
      const mock = await fixture(page, { auth: false, denied: 403 })
      mock.setOAuthOutcome(outcome)
      await page.setViewportSize({ width, height: 844 })
      await page.goto('/')
      const draft = 'Câu nháp đi qua Google'
      const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
      await input.fill(draft)
      await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click()
      await expect(page.getByRole('dialog', { name: 'Đăng nhập hoặc đăng ký', exact: true })).toBeVisible()
      expect(mock.oauthRequests).toHaveLength(0)
      await page.getByRole('button', { name: 'Tiếp tục bằng Google', exact: true }).click()
      await expect(page).toHaveURL(/\/login#.*error=/)
      await expect(page.getByRole('alert')).toContainText('Đăng nhập Google chưa hoàn tất hoặc đã bị hủy')
      await expect(page.getByRole('alert')).not.toContainText('private provider detail')
      expect(await page.evaluate(() => sessionStorage.getItem('vlu.pending-chat-question'))).toBe(draft)
      expect(mock.oauthRequests).toHaveLength(1)
      expect(mock.requests).toHaveLength(0)
      mock.setOAuthOutcome('success')
      if (outcome === 'cancel') {
        await page.goto('/')
        await expect(input).toHaveValue(draft)
        await page.getByRole('button', { name: 'Đăng nhập để gửi', exact: true }).click()
      }
      await page.getByRole('button', { name: 'Tiếp tục bằng Google', exact: true }).click()
      await expect(page).toHaveURL(/\/chat$/)
      await expect(input).toHaveValue(draft)
      await expect(page.locator('.chat-turn')).toHaveCount(0)
      expect(mock.oauthRequests).toHaveLength(2)
      expect(mock.requests.some(request => new URL(request.url()).pathname.startsWith('/questions'))).toBe(false)
      expect(await page.evaluate(() => sessionStorage.getItem('vlu.pending-chat-question'))).toBeNull()
    })
  }
}
