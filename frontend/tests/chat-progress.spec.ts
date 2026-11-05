import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { createServer } from 'node:http'
import type { ServerResponse } from 'node:http'
import { join } from 'node:path'
import { mkdir } from 'node:fs/promises'
import { fixture } from './fixtures'

const conversationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const historyId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
const stamp = '2026-11-05T09:00:00Z'
const reviewDir = process.env.CHAT_REVIEW_DIR ?? '../data/chat-progress-review'
const source = { citation: 1, chunk_id: 'chunk-1', document_id: 'document-1', filename: 'fixture.txt', chunk_index: 0, cosine_distance: .1 }
const answer = 'Câu trả lời đã được kiểm tra [1].'

async function streamingFixture(page: Page, history = false) {
  await fixture(page)
  await page.addInitScript(() => {
    document.addEventListener('animationstart', event => {
      if (event.animationName === 'answer-appear') document.documentElement.dataset.reveals = String(Number(document.documentElement.dataset.reveals ?? 0) + 1)
    })
  })
  const requests: { body: { request_id: string; question: string; conversation_id?: string }; response: ServerResponse; closed: boolean }[] = []
  let saved = false
  const server = createServer(async (request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*')
    response.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, Accept')
    response.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS')
    if (request.method === 'OPTIONS') { response.writeHead(204); response.end(); return }
    expect(request.headers.authorization).toMatch(/^Bearer /)
    const chunks: Buffer[] = []
    for await (const chunk of request) chunks.push(Buffer.from(chunk))
    const body = JSON.parse(Buffer.concat(chunks).toString())
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
    response.flushHeaders()
    const item = { body, response, closed: false }
    requests.push(item)
    response.on('close', () => { item.closed = true })
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  await page.route('**/questions/stream', route => route.continue({ url: `http://127.0.0.1:${address.port}/questions/stream` }))
  const conversation = (id: string, title: string) => ({ id, title, is_pinned: false, created_at: stamp, updated_at: stamp })
  await page.route('**/conversations', route => route.fulfill({ json: [
    ...(saved ? [conversation(conversationId, 'Hội thoại tiến trình')] : []),
    ...(history ? [conversation(historyId, 'Lịch sử dài')] : []),
  ] }))
  await page.route('**/conversations/*/messages', route => {
    const id = route.request().url().split('/').at(-2)!
    const count = id === historyId ? 35 : 1
    return route.fulfill({ json: Array.from({ length: count }, (_, index) => [
      { id: `user-${index}`, conversation_id: id, role: 'user', content: id === historyId ? `Câu hỏi cũ ${index}` : 'Câu hỏi kiểm thử', citations: null, created_at: stamp },
      { id: `assistant-${index}`, conversation_id: id, role: 'assistant', content: id === historyId ? `Nội dung lịch sử ${index}. `.repeat(12) : answer, citations: id === historyId ? [] : [source], created_at: stamp },
    ]).flat() })
  })
  return {
    requests,
    async received(index = 0) { await expect.poll(() => requests.length).toBeGreaterThan(index); return requests[index] },
    stage(index: number, stage: string) { requests[index].response.write(`event: progress\ndata: ${JSON.stringify({ request_id: requests[index].body.request_id, stage })}\n\n`) },
    success(index = 0) {
      saved = true
      const response = { answer, sources: [source], conversation_id: requests[index].body.conversation_id ?? conversationId }
      const frame = Buffer.from(`event: result\r\ndata: ${JSON.stringify({ request_id: requests[index].body.request_id, response })}\r\n\r\n`)
      // Deliberately split UTF-8 and SSE delimiters across network writes.
      const split = frame.indexOf(Buffer.from('được')) + 1
      requests[index].response.write(frame.subarray(0, split))
      requests[index].response.end(frame.subarray(split))
    },
    error(index = 0) { requests[index].response.end(`event: error\ndata: ${JSON.stringify({ request_id: requests[index].body.request_id, status: 503, detail: 'private provider detail' })}\n\n`) },
    async close() { for (const item of requests) item.response.destroy(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())) },
  }
}

async function send(page: Page) {
  const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
  await input.fill('Câu hỏi kiểm thử')
  await input.press('Enter')
}

for (const width of [1440, 390]) {
  test(`SSE HTTP mock: actual event labels, stable pulse, validated answer and one reveal at ${width}px`, async ({ page }) => {
    const mock = await streamingFixture(page)
    try {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
      await page.goto('/chat'); await send(page)
      const waiting = page.locator('.waiting-message')
      await expect(waiting).toHaveAttribute('role', 'status')
      await expect(waiting).toHaveText('Đang gửi câu hỏi…')
      const label = page.locator('.waiting-label')
      const shine = page.locator('.waiting-shine')
      await expect(shine).toHaveAttribute('aria-hidden', 'true')
      const foreground = await label.evaluate(element => getComputedStyle(element).color)
      expect(foreground).not.toBe('rgba(0, 0, 0, 0)')
      await expect.poll(() => shine.evaluate(element => getComputedStyle(element, '::after').animationName)).toBe('waiting-shimmer')
      const shineHandle = await shine.elementHandle()
      const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
      await expect(input).toBeFocused()
      await mock.received()
      const dot = await page.locator('.waiting-dot').elementHandle()
      await expect.poll(() => dot!.evaluate(element => element.getAnimations()[0]?.startTime)).not.toBeNull()
      const animationStart = await dot!.evaluate(element => element.getAnimations()[0].startTime)
      const transcript = page.getByRole('region', { name: 'Lịch sử hỏi đáp' })
      await transcript.focus()
      let height = 0
      for (const [stage, label] of [['query', 'Đang xử lý câu hỏi…'], ['retrieval', 'Đang tìm tài liệu…'], ['generation', 'Đang soạn câu trả lời…'], ['validation', 'Đang hoàn tất câu trả lời…']]) {
        mock.stage(0, stage)
        await expect(waiting).toHaveText(label)
        expect(await page.locator('.waiting-label').evaluate(element => getComputedStyle(element).color)).toBe(foreground)
        await expect(transcript).toBeFocused()
        expect(await dot!.evaluate(element => element === document.querySelector('.waiting-dot'))).toBe(true)
        expect(await dot!.evaluate(element => element.getAnimations()[0].startTime)).toBe(animationStart)
        const currentHeight = (await waiting.boundingBox())!.height
        if (height) expect(currentHeight).toBe(height)
        height = currentHeight
      }
      await mkdir(reviewDir, { recursive: true })
      await page.screenshot({ path: join(reviewDir, `chat-waiting-${width}.png`) })
      mock.success()
      await expect(page.locator('.answer-content')).toContainText(answer)
      await expect(page.getByRole('heading', { name: 'Nguồn tham chiếu', exact: true })).toBeVisible()
      await expect(page.locator('.waiting-dot')).toHaveCount(0)
      await expect(page.locator('.waiting-shine')).toHaveCount(0)
      expect(await shineHandle!.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
      await expect.poll(() => page.evaluate(() => document.documentElement.dataset.reveals)).toBe('1')
      await expect(page.locator('.answer-reveal')).toHaveCount(0)
      await expect(transcript).toBeFocused()
      expect(await dot!.evaluate(element => element.getAnimations().length)).toBe(0)
      await page.screenshot({ path: join(reviewDir, `chat-complete-${width}.png`) })
      if (width === 1440) {
        await expect(page.getByRole('button', { name: 'Hội thoại tiến trình', exact: true })).toBeVisible()
        await page.getByRole('button', { name: 'Cuộc trò chuyện mới', exact: true }).click()
        await page.getByRole('button', { name: 'Hội thoại tiến trình', exact: true }).click()
        await expect(page.locator('.answer-content')).toContainText(answer)
        expect(await page.evaluate(() => document.documentElement.dataset.reveals)).toBe('1')
        await page.reload()
        await page.getByRole('button', { name: 'Hội thoại tiến trình', exact: true }).click()
        await expect(page.locator('.answer-content')).toContainText(answer)
        expect(await page.evaluate(() => document.documentElement.dataset.reveals)).toBeUndefined()
        await expect(page.locator('.answer-reveal')).toHaveCount(0)
      }
    } finally { await mock.close() }
  })
}

for (const failure of ['error-event', 'disconnect']) {
  test(`SSE HTTP mock: ${failure} stops waiting, safe retry reuses request ID and turn`, async ({ page }) => {
    const mock = await streamingFixture(page)
    try {
      await page.goto('/chat'); await send(page); const first = await mock.received()
      mock.stage(0, 'query')
      await expect(page.locator('.waiting-message')).toHaveText('Đang xử lý câu hỏi…')
      if (failure === 'disconnect') first.response.destroy()
      else mock.error()
      await expect(page.locator('.message-error')).toBeVisible()
      await expect(page.locator('.message-error')).not.toContainText('private provider detail')
      await expect(page.locator('.waiting-dot')).toHaveCount(0)
      await expect(page.locator('.waiting-shine')).toHaveCount(0)
      await page.getByRole('button', { name: 'Thử lại', exact: true }).click()
      const retry = await mock.received(1)
      expect(retry.body).toEqual(first.body)
      await expect(page.locator('.user-message')).toHaveCount(1)
      mock.success(1)
      await expect(page.locator('.answer-content')).toContainText(answer)
      await expect(page.locator('.message-error')).toHaveCount(0)
    } finally { await mock.close() }
  })
}

test('SSE HTTP mock: reading history and switching conversations preserve scroll focus and isolate progress', async ({ page }) => {
  const mock = await streamingFixture(page, true)
  try {
    await page.goto('/chat')
    await page.getByRole('button', { name: 'Lịch sử dài', exact: true }).click()
    await expect(page.locator('.chat-turn')).toHaveCount(35)
    const transcript = page.getByRole('region', { name: 'Lịch sử hỏi đáp' })
    await transcript.evaluate(element => { element.scrollTop = element.scrollHeight })
    await send(page); await mock.received()
    await transcript.focus()
    await transcript.evaluate(element => { element.scrollTop = 120 })
    const before = await transcript.evaluate(element => element.scrollTop)
    for (const stage of ['query', 'retrieval', 'generation', 'validation']) {
      mock.stage(0, stage)
      await expect(page.locator('.waiting-message')).not.toHaveText('Đang gửi câu hỏi…')
      expect(await transcript.evaluate(element => element.scrollTop)).toBe(before)
    }
    mock.success()
    await expect(page.locator('.answer-content').last()).toContainText(answer)
    expect(await transcript.evaluate(element => element.scrollTop)).toBe(before)
    await expect(transcript).toBeFocused()
    await page.getByRole('button', { name: 'Cuộc trò chuyện mới', exact: true }).click()
    await send(page); await mock.received(1)
    mock.stage(1, 'query')
    await expect(page.locator('.waiting-message')).toHaveText('Đang xử lý câu hỏi…')
    await page.getByRole('button', { name: 'Lịch sử dài', exact: true }).click()
    await transcript.focus()
    await transcript.evaluate(element => { element.scrollTop = 200 })
    const scroll = await transcript.evaluate(element => element.scrollTop)
    const reveals = await page.evaluate(() => document.documentElement.dataset.reveals)
    mock.stage(1, 'generation'); mock.stage(1, 'validation'); mock.success(1)
    await expect(page.getByRole('button', { name: 'Hội thoại tiến trình', exact: true })).toBeVisible()
    expect(await transcript.evaluate(element => element.scrollTop)).toBe(scroll)
    await expect(page.locator('.waiting-message')).toHaveCount(0)
    await page.getByRole('button', { name: 'Hội thoại tiến trình', exact: true }).click()
    await expect(page.locator('.answer-content')).toContainText(answer)
    expect(await page.evaluate(() => document.documentElement.dataset.reveals)).toBe(reveals)
    await expect(page.locator('.answer-reveal')).toHaveCount(0)
  } finally { await mock.close() }
})

test('SSE HTTP mock: reduced motion is static and never replays completion after preference changes', async ({ page }) => {
  const mock = await streamingFixture(page)
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/chat'); await send(page); await mock.received()
    await expect(page.locator('.waiting-dot')).toHaveCSS('animation-name', 'none')
    expect(await page.locator('.waiting-shine').evaluate(element => getComputedStyle(element, '::after').animationName)).toBe('none')
    expect(await page.locator('.waiting-label').evaluate(element => getComputedStyle(element).color)).not.toBe('rgba(0, 0, 0, 0)')
    mock.stage(0, 'generation')
    await expect(page.locator('.waiting-message')).toHaveText('Đang soạn câu trả lời…')
    mock.success()
    await expect(page.locator('.answer-content')).toContainText(answer)
    await expect(page.locator('.answer-reveal')).toHaveCount(0)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    expect(await page.evaluate(() => document.documentElement.dataset.reveals)).toBeUndefined()
    await expect(page.locator('.waiting-dot')).toHaveCount(0)
  } finally { await mock.close() }
})

test('SSE HTTP mock: leaving chat aborts the active connection and removes waiting animation', async ({ page }) => {
  const mock = await streamingFixture(page)
  try {
    await page.goto('/chat'); await send(page); await mock.received()
    await page.getByRole('button', { name: 'Đăng xuất', exact: true }).click()
    await expect.poll(() => mock.requests[0].closed).toBe(true)
    await expect(page.locator('.waiting-dot')).toHaveCount(0)
    await expect(page.locator('.waiting-shine')).toHaveCount(0)
  } finally { await mock.close() }
})

test('SSE HTTP mock: shimmer travels left to right, keeps text readable and stops for reduced motion', async ({ page }) => {
  const mock = await streamingFixture(page)
  try {
    await page.goto('/chat'); await send(page); await mock.received()
    const label = page.locator('.waiting-label')
    const shine = page.locator('.waiting-shine')
    await expect(label).toHaveCSS('opacity', '1')
    await expect.poll(() => shine.evaluate(element => element.getAnimations({ subtree: true }).length)).toBeGreaterThan(0)
    const keyframes = await shine.evaluate(element => {
      const animation = element.getAnimations({ subtree: true }).find(item => item instanceof CSSAnimation && item.animationName === 'waiting-shimmer')
      return animation?.effect?.getKeyframes().map(frame => frame.backgroundPositionX ?? frame.backgroundPosition)
    })
    expect(keyframes?.[0]).toContain('100%')
    expect(keyframes?.at(-1)).toMatch(/^0%/)
    // A 300%-wide gradient starts its bright center off the left edge at
    // position 100%, then moves beyond the right edge at position 0%.
    const contrast = await label.evaluate(element => {
      const channels = getComputedStyle(element).color.match(/\d+/g)!.slice(0, 3).map(Number)
      const gradient = getComputedStyle(element.querySelector('.waiting-shine')!, '::after').backgroundImage
      const alpha = Number(gradient.match(/rgba\(255,\s*255,\s*255,\s*([\d.]+)\)/)![1])
      const highlighted = channels.map(value => (value * (1 - alpha) + 255 * alpha) / 255)
      let background = [1, 1, 1]
      for (let ancestor: Element | null = element; ancestor; ancestor = ancestor.parentElement) {
        const color = getComputedStyle(ancestor).backgroundColor
        if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') {
          background = color.match(/\d+/g)!.slice(0, 3).map(value => Number(value) / 255)
          break
        }
      }
      const luminance = (rgb: number[]) => rgb.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
        .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
      return (luminance(background) + .05) / (luminance(highlighted) + .05)
    })
    expect(contrast).toBeGreaterThanOrEqual(4.5)
    mock.stage(0, 'retrieval')
    await expect(page.getByRole('status')).toHaveText('Đang tìm tài liệu…')
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await expect(page.locator('.waiting-dot')).toHaveCSS('animation-name', 'none')
    await expect.poll(() => shine.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
    await expect(label).toHaveText('Đang tìm tài liệu…')
    mock.success()
    await expect(page.locator('.waiting-message')).toHaveCount(0)
  } finally { await mock.close() }
})

test('SSE HTTP mock: an event for another request fails safely and stops both waiting effects', async ({ page }) => {
  const mock = await streamingFixture(page)
  try {
    await page.goto('/chat'); await send(page); await mock.received()
    mock.requests[0].response.end(`event: result\ndata: ${JSON.stringify({ request_id: 'another-request', response: { answer: 'Foreign answer', sources: [], conversation_id: conversationId } })}\n\n`)
    await expect(page.locator('.message-error')).toBeVisible()
    await expect(page.locator('.waiting-dot')).toHaveCount(0)
    await expect(page.locator('.waiting-shine')).toHaveCount(0)
    await expect(page.locator('.answer-content')).toHaveCount(0)
    await expect(page.locator('.transcript')).not.toContainText('Foreign answer')
  } finally { await mock.close() }
})
