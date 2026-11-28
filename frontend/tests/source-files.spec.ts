import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { fixture } from './fixtures'

const conversationId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const documentId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const oldVersion = '11111111-aaaa-4aaa-8aaa-111111111111'
const newVersion = '22222222-aaaa-4aaa-8aaa-222222222222'
const pdfVersion = '33333333-aaaa-4aaa-8aaa-333333333333'
const stamp = '2026-11-05T09:00:00Z'
const pdfName = 'Sổ tay sinh viên.pdf'
const txtName = 'Quy định đăng ký học phần cho sinh viên Văn Lang.txt'
const webName = 'Cổng thông tin VLU'
const webUrl = 'https://vlu.example.test/sinh-vien/?term=1&year=2026#dang-ky'
const txtContent = 'Đăng ký học phần\n\n' + Array.from({ length: 36 }, (_, index) =>
  `Bước ${index + 1}. Kiểm tra mã học phần, số tín chỉ và lịch học trên cổng thông tin.`,
).join('\n\n')
const pdfFixture = new URL('./assets/student-handbook.pdf', import.meta.url)

async function historyFixture(page: Page, status = 200, pdfCitation: { filename: string; mime_type?: string } = {
  filename: pdfName, mime_type: 'application/pdf',
}) {
  await fixture(page)
  const requests: string[] = []
  const source = (citation: number, filename: string, version?: string) => ({
    citation, chunk_id: version ?? filename, document_id: documentId, filename,
    chunk_index: 0, cosine_distance: .1, source_file_version_id: version,
  })
  const history = [
    {
      question: 'Em cần làm gì để đăng ký học phần?',
      answer: 'Đọc **quy định đăng ký học phần** trước khi lập thời khóa biểu. [2, 1, 2]\n\n'
        + 'Lịch đăng ký được công bố trên [trang sinh viên](https://vlu.edu.vn/). [3]\n\n'
        + 'Dùng mã học phần `[1]` khi tra cứu. [4] [9]\n\n'
        + '```text\n[2] Mã học phần\n```',
      sources: [
        { ...source(1, pdfCitation.filename, pdfVersion), ...pdfCitation, page_start: 3, source_url: 'https://vlu.example.test/handbook.pdf' },
        { ...source(2, txtName, oldVersion), mime_type: 'text/plain', title: 'Đăng ký học phần' },
        { ...source(3, webName), source_url: webUrl },
        { ...source(4, pdfCitation.filename, pdfVersion), ...pdfCitation, page_start: 2 },
      ],
    },
    { question: 'Có bản cập nhật không?', answer: 'Đây là bản cập nhật. [1]', sources: [source(1, txtName, newVersion)] },
    { question: 'Quy định cũ thì sao?', answer: 'Đây là nguồn trích dẫn trước đây. [1]', sources: [source(1, 'Quy định cũ.txt')] },
  ]

  await page.route('**/conversations', route => route.fulfill({ json: [
    { id: conversationId, title: 'Lịch sử phiên bản', is_pinned: false, created_at: stamp, updated_at: stamp },
  ] }))
  await page.route('**/conversations/*/messages', route => route.fulfill({ json: history.flatMap((turn, index) => [
    { id: `user-${index}`, conversation_id: conversationId, role: 'user', content: turn.question, citations: null, created_at: stamp },
    { id: `answer-${index}`, conversation_id: conversationId, role: 'assistant', content: turn.answer, citations: turn.sources, created_at: stamp },
  ]) }))
  await page.route('**/source-files/*', async route => {
    expect(route.request().headers().authorization).toMatch(/^Bearer /)
    const version = route.request().url().split('/').at(-1)!
    requests.push(version)
    if (status !== 200) return route.fulfill({ status, json: { detail: 'private storage detail' } })
    if (version === pdfVersion) return route.fulfill({ contentType: 'application/pdf', body: await readFile(pdfFixture) })
    return route.fulfill({ contentType: 'text/plain; charset=utf-8', body: version === oldVersion ? txtContent : 'Nội dung cập nhật' })
  })
  await page.goto('/chat')
  await page.getByRole('button', { name: 'Lịch sử phiên bản', exact: true }).click()
  await expect(page.locator('.chat-turn')).toHaveCount(3)
  return { requests }
}

const openPanel = (page: Page) => page.getByRole('button', { name: 'Xem nguồn tham khảo', exact: true }).click()
const citation = (page: Page, name: string) => page.locator('.answer-content').getByRole('button', { name, exact: true })

test('inline citations follow their own sentences in marker order and preserve Markdown and web destinations', async ({ page, context }) => {
  const mock = await historyFixture(page)
  const answer = page.locator('.answer-content').first()
  const paragraphs = answer.locator(':scope > p')
  await expect(paragraphs.nth(0).locator('strong')).toHaveText('quy định đăng ký học phần')
  await expect(paragraphs.nth(0).locator('.citation-link')).toHaveText(['[2]', '[1]'])
  await expect(paragraphs.nth(1).getByRole('link', { name: 'trang sinh viên' })).toHaveAttribute('href', 'https://vlu.edu.vn/')
  const website = paragraphs.nth(1).getByRole('link', { name: `Mở trích dẫn 3 · ${webName}` })
  await expect(website).toHaveAttribute('href', webUrl)
  await expect(website).toHaveText('[3]')
  await context.route('https://vlu.example.test/**', route => route.fulfill({ body: 'Cổng thông tin fixture' }))
  const opened = page.waitForEvent('popup')
  await website.click()
  const tab = await opened
  await expect(tab).toHaveURL(webUrl)
  await tab.close()
  await expect(paragraphs.nth(2).locator('code')).toHaveText('[1]')
  await expect(paragraphs.nth(2)).toContainText('[9]')
  await expect(answer.locator('pre code')).toHaveText('[2] Mã học phần')
  await expect(answer.locator('.citation-link')).toHaveCount(4)
  await expect(page.getByRole('button', { name: 'Xem 3 nguồn', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('list', { name: 'Nguồn của câu trả lời' })).toHaveCount(0)
  expect(mock.requests).toEqual([])
})

test('reference toolbar retains direct downloads for both immutable versions', async ({ page }) => {
  const mock = await historyFixture(page)
  await openPanel(page)
  const panel = page.locator('#reference-sources-panel')
  await expect(panel).toContainText('Quy định cũ.txt')
  await expect(panel).toContainText('Chưa lưu tệp gốc')
  const buttons = panel.getByRole('button', { name: `Tải tệp gốc · ${txtName}`, exact: true })
  await expect(buttons).toHaveCount(2)
  for (const [index, content] of [txtContent, 'Nội dung cập nhật'].entries()) {
    const ready = page.waitForEvent('download')
    await buttons.nth(index).click()
    const download = await ready
    expect(download.suggestedFilename()).toBe(txtName)
    expect(await readFile((await download.path())!, 'utf8')).toBe(content)
  }
  expect(mock.requests).toEqual([oldVersion, newVersion])
})

test('source disclosure groups both PDF pages in one row and returns keyboard focus at 320px', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const mock = await historyFixture(page)
  await page.setViewportSize({ width: 320, height: 740 })
  const toggle = page.getByRole('button', { name: 'Xem 3 nguồn', exact: true })
  await toggle.press('Enter')
  await expect(toggle).toBeFocused()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const list = page.getByRole('list', { name: 'Nguồn của câu trả lời' })
  await expect(list.getByRole('listitem')).toHaveCount(3)
  await expect(list.getByRole('button', { name: '[2] Đăng ký học phần · TXT' })).toBeVisible()
  await expect(list.getByRole('button', { name: '[1] Sổ tay sinh viên · PDF · Trang 3' })).toBeVisible()
  await expect(list.getByRole('button', { name: /Tải tệp gốc/ })).toHaveCount(0)
  await expect(list).not.toContainText('Đoạn 0')
  await expect(list).toHaveCSS('transform', 'none')
  expect(await list.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)

  const pageTwo = list.getByRole('button', { name: '[4] Trang 2 · Sổ tay sinh viên' })
  await pageTwo.press('Enter')
  const dialog = page.getByRole('dialog', { name: pdfName })
  await expect(dialog.getByRole('img', { name: 'Trang 2', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(pageTwo).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(toggle).toBeFocused()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(list).toHaveCount(0)
  expect(mock.requests).toEqual([pdfVersion])
})

test('opening the same document from two answers previews each cited version', async ({ page }) => {
  const mock = await historyFixture(page)
  for (const [citationNumber, content] of [[2, txtContent], [1, 'Nội dung cập nhật']] as const) {
    await citation(page, `Mở trích dẫn ${citationNumber} · ${txtName}`).click()
    const dialog = page.getByRole('dialog', { name: txtName })
    await expect(dialog.locator('pre')).toHaveText(content)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  }
  expect(mock.requests).toEqual([oldVersion, newVersion])
})

test('PDF previews the cited page, downloads the original bytes and revokes the preview URL on close', async ({ page }) => {
  await page.addInitScript(() => {
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL = url => {
      document.documentElement.dataset.revokedPreview = url
      revoke(url)
    }
  })
  const mock = await historyFixture(page)
  const label = citation(page, `Mở trích dẫn 1 · ${pdfName}`)
  await label.press('Enter')
  const dialog = page.getByRole('dialog', { name: pdfName })
  const citedPage = dialog.getByRole('img', { name: 'Trang 3', exact: true })
  await expect(citedPage).toBeVisible()
  await expect(dialog.getByText('Trang 3 / 3', { exact: true })).toBeVisible()
  const isPageThree = await citedPage.evaluate((canvas: HTMLCanvasElement) => {
    // The fixture's navy bar is specific to page three. The other pages use red.
    const x = Math.round(60 * canvas.width / 595)
    const y = Math.round((842 - 768) * canvas.height / 842)
    const [red, , blue] = canvas.getContext('2d')!.getImageData(x, y, 1, 1).data
    return blue > red
  })
  expect(isPageThree).toBe(true)
  const downloadLink = dialog.getByRole('link', { name: 'Tải tệp gốc' })
  const url = (await downloadLink.getAttribute('href'))!
  expect(url).toMatch(/^blob:/)
  await expect(dialog.getByRole('link', { name: 'Mở trong tab mới' })).toHaveAttribute('href', `${url}#page=3`)
  await page.screenshot({ path: 'test-results/inline-source-previews/chat-pdf-desktop.png', animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/inline-source-previews/chat-pdf-mobile.png', animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Trang trước', exact: true }).click()
  await expect(dialog.getByRole('img', { name: 'Trang 2', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Trang sau', exact: true }).click()
  await expect(citedPage).toBeVisible()
  const ready = page.waitForEvent('download')
  await downloadLink.click()
  const download = await ready
  expect(download.suggestedFilename()).toBe(pdfName)
  expect(await readFile((await download.path())!)).toEqual(await readFile(pdfFixture))
  await dialog.getByRole('button', { name: 'Đóng', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(label).toBeFocused()
  await expect(page.locator('html')).toHaveAttribute('data-revoked-preview', url)
  expect(mock.requests).toEqual([pdfVersion])
})

test('PDF preview uses the stored MIME type when the citation has no file type hint', async ({ page }) => {
  const filename = 'Sổ tay sinh viên'
  const mock = await historyFixture(page, 200, { filename })
  await citation(page, `Mở trích dẫn 1 · ${filename}`).click()
  const dialog = page.getByRole('dialog', { name: filename, exact: true })
  await expect(dialog.getByRole('img', { name: 'Trang 3', exact: true })).toBeVisible()
  expect(mock.requests).toEqual([pdfVersion])
})

test('PDF fallback keeps the original page in the new tab link when inline PDF is unavailable', async ({ page }) => {
  const mock = await historyFixture(page)
  await page.route('**/pdf.worker.min.mjs*', route => route.abort())
  await openPanel(page)
  await page.locator('#reference-sources-panel').getByRole('button', { name: /Sổ tay sinh viên.*Trang 3.*Xem trước/ }).click()
  const dialog = page.getByRole('dialog', { name: pdfName })
  await expect(dialog.getByRole('alert')).toContainText('Không thể hiển thị PDF')
  const fallback = dialog.getByRole('link', { name: 'Mở trong tab mới' })
  await expect(fallback).toHaveAttribute('href', /^blob:.*#page=3$/)
  await expect(fallback).toHaveAttribute('target', '_blank')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('#reference-sources-panel')).toBeVisible()
  expect(mock.requests).toEqual([pdfVersion])
})

for (const [viewport, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]] as const) {
  test(`TXT previews scrollable content and downloads the original on ${viewport}`, async ({ page }) => {
    const mock = await historyFixture(page)
    await page.setViewportSize({ width, height })
    const label = citation(page, `Mở trích dẫn 2 · ${txtName}`)
    await page.locator('.answer-content').first().scrollIntoViewIfNeeded()
    await expect(label).toHaveAttribute('title', txtName)
    await expect(label).toHaveText('[2]')
    if (viewport === 'mobile') {
      await label.press('Tab')
      await page.keyboard.press('Shift+Tab')
      await expect(label).toBeFocused()
      await expect(label).toHaveCSS('outline-style', 'solid')
      await expect(label).toHaveAccessibleName(`Mở trích dẫn 2 · ${txtName}`)
      await label.blur()
    }
    await page.screenshot({ path: `test-results/inline-source-previews/chat-sources-${viewport}.png`, animations: 'disabled' })
    await label.click()
    const dialog = page.getByRole('dialog', { name: txtName })
    const body = dialog.locator('pre')
    await expect(body).toHaveText(txtContent)
    expect(await body.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true)
    await expect(dialog.getByRole('link', { name: 'Tải tệp gốc' })).toBeInViewport()
    await page.screenshot({ path: `test-results/inline-source-previews/chat-txt-${viewport}.png`, animations: 'disabled' })
    const ready = page.waitForEvent('download')
    await dialog.getByRole('link', { name: 'Tải tệp gốc' }).click()
    const download = await ready
    expect(download.suggestedFilename()).toBe(txtName)
    expect(await readFile((await download.path())!, 'utf8')).toBe(txtContent)
    expect(mock.requests).toEqual([oldVersion])
  })
}

test('old citations show the filename and missing-file message without requesting a file', async ({ page }) => {
  const mock = await historyFixture(page)
  const oldAnswer = page.locator('.chat-turn').last()
  await oldAnswer.getByRole('button', { name: 'Xem 1 nguồn' }).click()
  const list = oldAnswer.getByRole('list', { name: 'Nguồn của câu trả lời' })
  await expect(list).toContainText('Quy định cũ')
  await expect(list).toContainText('Chưa có tệp gốc để xem')
  await expect(list.getByRole('button')).toHaveCount(0)
  await citation(page, 'Mở trích dẫn 1 · Quy định cũ.txt').click()
  const dialog = page.getByRole('dialog', { name: 'Quy định cũ.txt' })
  await expect(dialog.getByRole('status')).toContainText('Chưa lưu tệp gốc')
  await expect(dialog.getByRole('link', { name: 'Tải tệp gốc' })).toHaveCount(0)
  expect(mock.requests).toEqual([])
})

test('failed previews display a safe error and can be closed', async ({ page }) => {
  const mock = await historyFixture(page, 404)
  await citation(page, `Mở trích dẫn 1 · ${pdfName}`).click()
  const dialog = page.getByRole('dialog', { name: pdfName })
  await expect(dialog.getByRole('alert')).toContainText('Không thể mở tệp gốc')
  await expect(dialog.getByRole('alert')).not.toContainText('private storage detail')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.chat-turn')).toHaveCount(3)
  await openPanel(page)
  await page.locator('#reference-sources-panel').getByRole('button', { name: `Tải tệp gốc · ${pdfName}`, exact: true }).first().click()
  await expect(page.getByRole('alert')).toContainText('Không thể mở tệp gốc')
  await expect(page.getByRole('alert')).not.toContainText('private storage detail')
  expect(mock.requests).toEqual([pdfVersion, pdfVersion])
})

test('preview distinguishes a 503 and can reopen the same PDF after service recovery', async ({ page }) => {
  const mock = await historyFixture(page, 503)
  const label = citation(page, `Mở trích dẫn 1 · ${pdfName}`)
  await label.press('Enter')
  const dialog = page.getByRole('dialog', { name: pdfName })
  const alert = dialog.getByRole('alert')
  await expect(alert).toHaveText('Máy chủ hiện chưa thể tải tệp gốc. Hãy thử mở lại sau.')
  await expect(dialog.getByRole('link', { name: 'Tải tệp gốc' })).toHaveCount(0)
  expect(mock.requests).toEqual([pdfVersion])
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(label).toBeFocused()

  await page.route(`**/source-files/${pdfVersion}`, async route => {
    mock.requests.push(pdfVersion)
    await route.fulfill({ contentType: 'application/pdf', body: await readFile(pdfFixture) })
  })
  await label.press('Enter')
  await expect(dialog.getByRole('img', { name: 'Trang 3', exact: true })).toBeVisible()
  await expect(dialog.getByRole('link', { name: 'Tải tệp gốc' })).toBeVisible()
  expect(mock.requests).toEqual([pdfVersion, pdfVersion])
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
  await expect(turn.locator('.answer-content').getByRole('button', { name: 'Mở trích dẫn 1 · legacy.pdf' })).toHaveText('[1]')
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
  await expect(turn.locator('.answer-content').getByRole('button', { name: 'Mở trích dẫn 1 · legacy.pdf' })).toHaveText('[1]')
  await expect(turn.getByText(expiry)).toBeVisible()
  await expect(grounding).toHaveCount(0)
})
