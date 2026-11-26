import { expect, test } from '@playwright/test'
import type { Download, Page } from '@playwright/test'
import { fixture } from './fixtures'

const conversationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const documentId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const oldVersion = '11111111-aaaa-4aaa-8aaa-111111111111'
const newVersion = '22222222-aaaa-4aaa-8aaa-222222222222'
const stamp = '2026-11-05T09:00:00Z'

async function historyFixture(page: Page, mime = 'text/plain', status = 200, openPanel = true) {
  await fixture(page)
  const file = mime === 'application/pdf' ? 'source.pdf' : 'source.txt'
  const requests: string[] = []
  const source = (version?: string, index = 0) => ({
    citation: 1, chunk_id: `chunk-${index}`, document_id: documentId,
    filename: version ? file : 'legacy.txt', chunk_index: index, cosine_distance: .1,
    ...(version ? { source_file_version_id: version, mime_type: mime, page_start: mime === 'application/pdf' ? 3 : null } : {}),
  })
  const sources = [source(oldVersion), source(newVersion, 1), source(undefined, 2)]
  await page.route('**/conversations', route => route.fulfill({ json: [{ id: conversationId, title: 'Lịch sử phiên bản', is_pinned: false, created_at: stamp, updated_at: stamp }] }))
  await page.route('**/conversations/*/messages', route => route.fulfill({ json: sources.flatMap((citation, index) => [
    { id: `user-${index}`, conversation_id: conversationId, role: 'user', content: `Câu hỏi ${index + 1}`, citations: null, created_at: stamp },
    { id: `answer-${index}`, conversation_id: conversationId, role: 'assistant', content: `Câu trả lời ${index + 1} [1].`, citations: [citation], created_at: stamp },
  ]) }))
  await page.route('**/source-files/*', route => {
    expect(route.request().headers().authorization).toMatch(/^Bearer /)
    const version = route.request().url().split('/').at(-1)!
    requests.push(version)
    if (status !== 200) return route.fulfill({ status, json: { detail: 'private storage detail' } })
    return route.fulfill({ contentType: mime, body: version === oldVersion ? 'original bytes' : 'replacement bytes' })
  })
  await page.goto('/chat')
  await page.getByRole('button', { name: 'Lịch sử phiên bản', exact: true }).click()
  await expect(page.locator('.chat-turn')).toHaveCount(3)
  if (openPanel) await page.getByRole('button', { name: 'Xem nguồn tham khảo', exact: true }).click()
  return { requests }
}

async function downloadedText(download: Download) {
  const stream = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(Buffer.from(chunk))
  return Buffer.concat(chunks).toString()
}

test('file mock: two citations to the same document download their own TXT version; legacy citations remain visible', async ({ page }) => {
  const mock = await historyFixture(page)
  await expect(page.locator('.reference-sources-list')).toContainText('legacy.txt')
  await expect(page.locator('.reference-sources-list')).toContainText('Chưa lưu file gốc')
  const buttons = page.locator('.reference-sources-list button')
  await expect(buttons).toHaveCount(2)
  for (const [index, content] of ['original bytes', 'replacement bytes'].entries()) {
    const ready = page.waitForEvent('download')
    await buttons.nth(index).click()
    const download = await ready
    expect(download.suggestedFilename()).toBe('source.txt')
    expect(await downloadedText(download)).toBe(content)
  }
  expect(mock.requests).toEqual([oldVersion, newVersion])
})

async function capturePdfWindow(page: Page) {
  await page.addInitScript(() => {
    window.open = () => ({
      set opener(value: unknown) { document.documentElement.dataset.originalOpener = String(value) },
      location: { set href(value: string) { document.documentElement.dataset.originalUrl = value } },
      close() { document.documentElement.dataset.originalClosed = 'true' },
    }) as unknown as Window
    URL.createObjectURL = blob => {
      void (blob as Blob).text().then(value => { document.documentElement.dataset.originalContent = value })
      return 'blob:http://127.0.0.1:5178/isolated-pdf'
    }
  })
}

test('file mock: PDF opens the cited immutable version at its original page', async ({ page }) => {
  await capturePdfWindow(page)
  const mock = await historyFixture(page, 'application/pdf')
  await page.locator('.reference-sources-list button').first().click()
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.originalUrl)).toBe('blob:http://127.0.0.1:5178/isolated-pdf#page=3')
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.originalContent)).toBe('original bytes')
  expect(await page.evaluate(() => document.documentElement.dataset.originalOpener)).toBe('null')
  expect(mock.requests).toEqual([oldVersion])
})

test('the citation marker and its reference card open the corresponding PDF page', async ({ page }) => {
  await capturePdfWindow(page)
  const mock = await historyFixture(page, 'application/pdf', 200, false)
  const citationName = { name: 'Mở trích dẫn 1 · source.pdf', exact: true }
  await page.locator('.answer-content').first().getByRole('button', citationName).press('Enter')
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.originalUrl)).toContain('#page=3')
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.originalContent)).toBe('original bytes')

  const replacement = page.locator('.answer-sources').nth(1)
  await expect(replacement.getByText('Trang 3', { exact: true })).toBeVisible()
  await replacement.getByRole('button', citationName).click()
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.originalContent)).toBe('replacement bytes')
  expect(mock.requests).toEqual([oldVersion, newVersion])
  await expect(page.locator('.answer-content').last().getByRole('button')).toHaveCount(0)
})

test('a text citation displays the original TXT in a new tab', async ({ page }) => {
  const mock = await historyFixture(page, 'text/plain', 200, false)
  const ready = page.waitForEvent('popup')
  await page.locator('.answer-content').first().getByRole('button', { name: 'Mở trích dẫn 1 · source.txt' }).click()
  const popup = await ready
  await expect(popup.locator('body')).toHaveText('original bytes')
  expect(mock.requests).toEqual([oldVersion])
  await popup.close()
})

test('file mock: unavailable or unauthorized originals show a safe error and preserve old citations', async ({ page }) => {
  await capturePdfWindow(page)
  const mock = await historyFixture(page, 'application/pdf', 404)
  await page.locator('.reference-sources-list button').first().click()
  await expect(page.getByRole('alert')).toContainText('Không thể mở file gốc')
  await expect(page.getByRole('alert')).not.toContainText('private storage detail')
  expect(await page.evaluate(() => document.documentElement.dataset.originalClosed)).toBe('true')
  await expect(page.locator('.chat-turn')).toHaveCount(3)
  await expect(page.locator('.reference-sources-list')).toContainText('legacy.txt')
  expect(mock.requests).toEqual([oldVersion])
})

test('live grounding preserves text and displays Search Suggestions, and reload expires the whole block', async ({ page, context }) => {
  await fixture(page)
  const url = 'https://grounding.example.test/weather?z=2&a=1'
  const searchUrl = 'https://www.google.com/search?q=thoi+tiet'
  const answer = 'Nội bộ [1].'
  const text = '  Mưa rào.\nTrời mát.\n'
  const expiry = 'Kết quả tra cứu web đã hết hạn khi xem lại cuộc trò chuyện.'
  const source = { citation: 1, chunk_id: 'legacy', document_id: documentId, filename: 'legacy.pdf',
    chunk_index: 0, cosine_distance: null }
  let saved = false
  await context.route(url, route => route.fulfill({ contentType: 'text/plain', body: 'Mock weather source' }))
  await context.route(searchUrl, route => route.fulfill({ contentType: 'text/plain', body: 'Mock search results' }))
  await page.route('**/questions/stream', route => {
    saved = true
    const { request_id } = route.request().postDataJSON()
    return route.fulfill({ contentType: 'text/event-stream', body: 'event: result\ndata: ' + JSON.stringify({
      request_id, response: {
        answer, sources: [source], conversation_id: conversationId,
        grounding: {
          text, sources: [{ title: 'Bản tin thời tiết', url }],
          search_suggestions_html: '<style>.chip { color: rgb(12, 34, 56); }</style>'
            + '<a class="chip" href="' + searchUrl + '" target="_blank">Thời tiết hôm nay</a>',
        },
      },
    }) + '\n\n' })
  })
  await page.route('**/conversations', route => route.fulfill({ json: saved ? [{
    id: conversationId, title: 'Tra cứu hỗn hợp', is_pinned: false, created_at: stamp, updated_at: stamp,
  }] : [] }))
  await page.route('**/conversations/*/messages', route => route.fulfill({ json: [
    { id: 'user', conversation_id: conversationId, role: 'user', content: 'Quy định và thời tiết', citations: null, created_at: stamp },
    { id: 'assistant', conversation_id: conversationId, role: 'assistant', content: answer + '\n\n' + expiry,
      created_at: stamp, citations: [source],
    },
  ] }))

  await page.goto('/chat')
  const input = page.getByRole('textbox', { name: 'Câu hỏi của bạn', exact: true })
  await input.fill('Quy định và thời tiết')
  await input.press('Enter')
  const turn = page.locator('.chat-turn')
  const grounding = turn.getByRole('region', { name: 'Thông tin cập nhật từ Google Search' })
  await expect(grounding).toBeVisible()
  expect(await grounding.locator('p').textContent()).toBe(text)
  await expect(grounding.locator('iframe')).toHaveCount(0)
  await expect(turn.getByText('legacy.pdf')).toBeVisible()
  const suggestion = grounding.getByRole('link', { name: 'Thời tiết hôm nay', exact: true })
  await expect(suggestion).toBeVisible()
  await expect(suggestion).toHaveCSS('color', 'rgb(12, 34, 56)')
  for (const [link, destination, body] of [
    [grounding.getByRole('link', { name: 'Bản tin thời tiết' }), url, 'Mock weather source'],
    [suggestion, searchUrl, 'Mock search results'],
  ] as const) {
    const opened = page.waitForEvent('popup')
    await link.click()
    const popup = await opened
    await expect(popup).toHaveURL(destination)
    await expect(popup.locator('body')).toHaveText(body)
    await popup.close()
  }
  await page.reload()
  await page.getByRole('button', { name: 'Tra cứu hỗn hợp', exact: true }).click()
  await expect(turn.getByText('legacy.pdf')).toBeVisible()
  await expect(turn.getByText(expiry)).toBeVisible()
  await expect(grounding).toHaveCount(0)
})
