import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import type { AdminStatistics } from '../src/admin/adminApi'
import { emptyStatistics, fixture, signIn } from './admin-fixtures'

const statisticsApi = 'http://127.0.0.1:48080/admin/statistics?*'
const longFilename = 'QuyCheHocVuVaChuongTrinhDaoTao'.repeat(6) + '.pdf'
const sample: AdminStatistics = {
  start_date: '2026-11-13',
  end_date: '2026-11-20',
  timezone: 'Asia/Ho_Chi_Minh',
  data_started_at: '2026-11-10T18:00:00Z',
  outcome_denominator: 20,
  daily_classified: [null, 0, 6, 4, 5, 3, 2].map((count, index) => ({
    date: '2026-11-' + (13 + index), count,
  })),
  unclassified: 4,
  running: 2,
  cancelled: 1,
  by_outcome: {
    answered: { count: 10, ratio: 0.5 },
    partial: { count: 5, ratio: 0.25 },
    insufficient_evidence: { count: 3, ratio: 0.15 },
    clarification: { count: 1, ratio: 0.05 },
    unavailable: { count: 0, ratio: 0 },
    error: { count: 1, ratio: 0.05 },
  },
  by_executed_route: {
    internal: { count: 20, ratio: 1 }, general: { count: 0, ratio: 0 },
    web: { count: 0, ratio: 0 }, mixed: { count: 0, ratio: 0 }, none: { count: 0, ratio: 0 },
  },
  cited_answer_denominator: 9,
  ranked_documents: [
    { document_id: 'doc-1', filename: longFilename, deleted: false, count: 7, ratio: 7 / 9 },
    { document_id: 'doc-2', filename: 'Quy chế cũ.pdf', deleted: true, count: 3, ratio: 3 / 9 },
  ],
}
const unmeasured: AdminStatistics = { ...sample, ...emptyStatistics }

function dates(route: Route) {
  const { searchParams } = new URL(route.request().url())
  return { from: searchParams.get('from')!, to: searchParams.get('to')! }
}

async function reply(route: Route, report: AdminStatistics = sample) {
  expect(route.request().method()).toBe('GET')
  expect(route.request().headers().authorization).toMatch(/^Bearer .+\.fixture$/)
  const { from, to } = dates(route)
  await route.fulfill({ json: { ...report, start_date: from, end_date: to } })
}

function summary(page: Page) {
  return page.locator('dl[aria-label="Tổng quan"]')
}

test.use({ timezoneId: 'America/Los_Angeles', reducedMotion: 'reduce' })

test('giữ trang mặc định, đọc số liệu và xếp hai khối cạnh nhau trên desktop', async ({ page }, info) => {
  await fixture(page)
  await page.route(statisticsApi, route => reply(route))
  await page.goto('/admin')
  const sidebar = page.getByRole('navigation', { name: 'Điều hướng quản trị' })
  const overviewLink = sidebar.getByRole('link', { name: 'Tổng quan' })
  const sourcesLink = sidebar.getByRole('link', { name: 'Quản lý tài liệu' })
  const breadcrumb = page.getByRole('navigation', { name: 'Vị trí hiện tại' })
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page).toHaveTitle('Quản trị · Văn Lang')
  await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
  await expect(overviewLink).toHaveAttribute('aria-current', 'page')
  await expect(sourcesLink).not.toHaveAttribute('aria-current', 'page')
  await expect(breadcrumb).toHaveText('Quản trị / Tổng quan')
  await expect(page.getByRole('banner').getByText('VLU · Quản trị', { exact: true })).toBeVisible()
  await expect(page.getByRole('banner')).not.toContainText(/\b(?:rag|chatbot)\b/i)
  const help = page.getByRole('button', { name: 'Cách đọc số liệu' })
  const explanation = page.getByText('Thống kê quá trình xử lý, không phản ánh độ chính xác của câu trả lời.')
  await expect(explanation).toHaveCount(0)
  await help.press('Enter')
  const helpDialog = page.getByRole('dialog', { name: 'Cách đọc số liệu' })
  await expect(helpDialog).toBeVisible()
  await expect(explanation).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(helpDialog).toHaveCount(0)
  await expect(help).toBeFocused()
  await expect(page.getByText('Giờ Việt Nam', { exact: true })).toHaveCount(0)
  await expect(summary(page).locator('.admin-statistics__value')).toHaveText(['20', '10', '5'])
  await expect(summary(page).locator('.admin-statistics__rate')).toHaveText(['50%', '25%'])
  await expect(summary(page)).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  const metrics = summary(page).locator('.admin-statistics__metric')
  await expect(metrics.first()).toHaveCSS('border-right-width', '1px')
  await expect(metrics.first()).toHaveCSS('border-bottom-width', '0px')
  const [total, answered, partial] = await metrics.evaluateAll(items => items.map(item => {
    const { x, y } = item.getBoundingClientRect()
    const size = Number.parseFloat(getComputedStyle(item.querySelector('dd')!).fontSize)
    return { x, y, size }
  }))
  expect(total.y).toBe(answered.y)
  expect(answered.y).toBe(partial.y)
  expect(total.x).toBeLessThan(answered.x)
  expect(answered.x).toBeLessThan(partial.x)
  expect(total.size).toBeGreaterThan(answered.size)
  const outcomes = page.getByRole('region', { name: 'Kết quả xử lý' })
  await expect(outcomes).toContainText('Tỷ lệ tính trên 20 lượt đã kết thúc và được phân loại.')
  await expect(outcomes.getByRole('listitem')).toHaveText([
    'Đã trả lời đủ đầu mục10 lượt50%', 'Trả lời một phần5 lượt25%', 'Thiếu bằng chứng3 lượt15%',
    'Cần làm rõ1 lượt5%', 'Không khả dụng0 lượt0%', 'Lỗi xử lý1 lượt5%',
  ])
  const barColors = {
    answered: 'rgb(21, 128, 61)',
    partial: 'rgb(166, 107, 0)',
    insufficient_evidence: 'rgb(166, 107, 0)',
    clarification: 'rgb(100, 116, 139)',
    error: 'rgb(198, 45, 63)',
  }
  for (const [outcome, color] of Object.entries(barColors)) {
    await expect(outcomes.locator('[data-outcome="' + outcome + '"] .admin-statistics__bar')).toHaveCSS('background-color', color)
  }
  await expect(outcomes.locator('[data-outcome="unavailable"] .admin-statistics__bar')).toHaveCount(0)
  const coverage = page.locator('dl[aria-label="Phạm vi ghi nhận"]')
  await expect(coverage.locator('dt')).toHaveText(['Chưa phân loại', 'Chưa kết thúc', 'Đã hủy'])
  await expect(coverage.locator('dd').first()).toHaveText('4')
  await expect(coverage.locator('dd').nth(1)).toHaveText('2')

  const daily = page.getByRole('region', { name: 'Lượt đã kết thúc và được phân loại theo ngày' })
  await expect(daily.locator('.admin-statistics__day > span')).toHaveText(['—', '0', '6', '4', '5', '3', '2'])
  await expect(daily.locator('.admin-statistics__day').first().locator('.admin-statistics__day-bar')).toHaveCount(0)
  await expect(daily.locator('.admin-statistics__day-bar[data-zero]')).toHaveCount(1)
  await daily.getByText('Xem bảng theo ngày').click()
  const dayTable = daily.getByRole('table')
  await expect(dayTable.getByRole('cell')).toHaveText(['Chưa có số liệu', '0', '6', '4', '5', '3', '2'])
  await expect(dayTable.locator('time').first()).toHaveAttribute('datetime', '2026-11-13')
  await daily.getByText('Xem bảng theo ngày').click()

  const documents = page.getByRole('region', { name: 'Tài liệu được trích dẫn nhiều' })
  const table = documents.getByRole('table')
  await expect(table.getByRole('rowheader')).toHaveText([longFilename, 'Quy chế cũ.pdfĐã xóa'])
  await expect(table.locator('td span:first-child')).toHaveText(['7', '3'])
  await expect(table.locator('td span:last-child')).toHaveText(['77,8%', '33,3%'])
  const widths = await table.locator('.admin-statistics__bar').evaluateAll(bars =>
    bars.map(bar => Number.parseFloat((bar as HTMLElement).style.width)))
  expect(widths[0]).toBeCloseTo(7 / 9 * 100)
  expect(widths[1]).toBeCloseTo(3 / 9 * 100)
  await expect(documents).toContainText('9 câu trả lời có trích dẫn tài liệu nội bộ.')
  await expect(documents).toContainText('chỉ tính một lần')
  await expect(documents).toContainText('Thống kê vận hành đã ghi được giữ lại')
  const outcomeBox = (await outcomes.boundingBox())!
  const documentBox = (await documents.boundingBox())!
  expect(documentBox.y).toBeCloseTo(outcomeBox.y, 0)
  expect(documentBox.x).toBeGreaterThan(outcomeBox.x + outcomeBox.width)
  await page.screenshot({ path: info.outputPath('dashboard-desktop.png') })

  await sourcesLink.click()
  await expect(page).toHaveURL(/\/admin\/sources$/)
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu' })).toBeVisible()
  await expect(page).toHaveTitle('Quản trị · Văn Lang')
  await expect(sourcesLink).toHaveAttribute('aria-current', 'page')
  await expect(overviewLink).not.toHaveAttribute('aria-current', 'page')
  await expect(breadcrumb).toHaveText('Quản trị / Quản lý tài liệu')
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/admin$/)
  await page.reload()
  await expect(summary(page).locator('.admin-statistics__value')).toHaveText(['20', '10', '5'])
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu' })).toBeVisible()
  await expect(page).toHaveURL(/\/admin\/sources$/)
})

test('chỉ tô nhãn tỷ lệ dương và giữ 0% trên nền trung tính', async ({ page }) => {
  let report = sample
  await fixture(page)
  await page.route(statisticsApi, route => reply(route, report))
  await page.goto('/admin')
  const rates = summary(page).locator('.admin-statistics__rate')
  await expect(rates).toHaveText(['50%', '25%'])
  await expect(rates.nth(0)).toHaveCSS('background-color', 'rgb(231, 245, 235)')
  await expect(rates.nth(0)).toHaveCSS('color', 'rgb(22, 101, 52)')
  await expect(rates.nth(1)).toHaveCSS('background-color', 'rgb(255, 243, 207)')
  await expect(rates.nth(1)).toHaveCSS('color', 'rgb(119, 78, 9)')
  const metrics = summary(page).locator('.admin-statistics__metric')
  for (const index of [0, 1, 2]) {
    await expect(metrics.nth(index)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  }

  report = { ...sample, by_outcome: {
    ...sample.by_outcome, answered: { count: 5, ratio: 0.25 }, partial: { count: 10, ratio: 0.5 },
  } }
  await page.getByRole('button', { name: '30 ngày' }).click()
  await expect(rates).toHaveText(['25%', '50%'])
  await expect(rates.nth(0)).toHaveCSS('background-color', 'rgb(231, 245, 235)')
  await expect(rates.nth(1)).toHaveCSS('background-color', 'rgb(255, 243, 207)')

  report = { ...sample, by_outcome: {
    ...sample.by_outcome, answered: { count: 0, ratio: 0 }, partial: { count: 0, ratio: 0 },
    insufficient_evidence: { count: 18, ratio: 0.9 },
  } }
  await page.getByRole('button', { name: '7 ngày' }).click()
  await expect(rates).toHaveText(['0%', '0%'])
  await expect(rates.nth(0)).toHaveCSS('background-color', 'rgb(243, 244, 248)')
  await expect(rates.nth(1)).toHaveCSS('background-color', 'rgb(243, 244, 248)')
  const emptyRows = page.locator('[data-outcome="answered"], [data-outcome="partial"]')
  await expect(emptyRows.locator('.admin-statistics__track')).toHaveCount(2)
  await expect(emptyRows.locator('.admin-statistics__bar')).toHaveCount(0)
})

test('phân biệt chưa đo, mẫu số 0, lượt chưa phân loại và chưa kết thúc', async ({ page }) => {
  const stats = { ...unmeasured }
  await fixture(page)
  await page.route(statisticsApi, route => reply(route, stats))
  await page.goto('/admin')
  await expect(page.getByText('Chưa có dữ liệu được đo.')).toBeVisible()
  await expect(summary(page).locator('.admin-statistics__value')).toHaveText(['0', '—', '—'])
  await expect(summary(page).locator('.admin-statistics__rate')).toHaveText(['—', '—'])
  const rates = summary(page).locator('.admin-statistics__rate')
  await expect(rates.nth(0)).toHaveCSS('background-color', 'rgb(243, 244, 248)')
  await expect(rates.nth(1)).toHaveCSS('background-color', 'rgb(243, 244, 248)')
  const outcomes = page.getByRole('region', { name: 'Kết quả xử lý' })
  await expect(outcomes.locator('.admin-statistics__outcome-rate')).toHaveText(Array(6).fill('—'))
  await expect(outcomes.locator('.admin-statistics__track')).toHaveCount(6)
  await expect(outcomes.locator('.admin-statistics__bar')).toHaveCount(0)
  await expect(page.getByText('Không có câu trả lời có trích dẫn tài liệu nội bộ trong khoảng này.')).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)

  Object.assign(stats, { data_started_at: sample.data_started_at, unclassified: 3, running: 1 })
  await page.getByRole('button', { name: '30 ngày' }).click()
  await expect(page.getByText('Không có lượt đã kết thúc và được phân loại trong khoảng này.')).toBeVisible()
  await expect(page.locator('dl[aria-label="Phạm vi ghi nhận"] dd').first()).toHaveText('3')
  await expect(page.locator('dl[aria-label="Phạm vi ghi nhận"] dd').nth(1)).toHaveText('1')
  await expect(summary(page).locator('.admin-statistics__rate')).toHaveText(['—', '—'])
})

test('dùng ngày Việt Nam, giữ khoảng [từ, đến) và bỏ qua phản hồi cũ', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-18T17:05:00Z'))
  await fixture(page)
  await page.addInitScript(() => {
    const fetchRequest = window.fetch
    // Let the old HTTP response arrive even after the component cancels it.
    window.fetch = (input, init) => fetchRequest(input, String(input).includes('/admin/statistics?')
      ? { ...init, signal: undefined } : init)
  })
  const seen: ReturnType<typeof dates>[] = []
  let releaseOld!: () => void
  const oldResponse = new Promise<void>(resolve => { releaseOld = resolve })
  await page.route(statisticsApi, async route => {
    const range = dates(route)
    seen.push(range)
    if (range.from === '2026-11-13') {
      await oldResponse
      await reply(route, { ...unmeasured, unclassified: 99 })
      return
    }
    await reply(route)
  })

  await page.goto('/admin')
  await expect(page.getByRole('status')).toHaveText('Đang tải số liệu thống kê…')
  await expect.poll(() => seen).toContainEqual({ from: '2026-11-13', to: '2026-11-20' })
  await page.getByRole('button', { name: '30 ngày' }).click()
  await expect(summary(page).locator('.admin-statistics__value').first()).toHaveText('20')
  expect(seen.at(-1)).toEqual({ from: '2026-10-21', to: '2026-11-20' })
  const oldArrived = page.waitForResponse(response => response.url().includes('from=2026-11-13'))
  releaseOld()
  await (await oldArrived).finished()

  await page.getByRole('button', { name: 'Tùy chọn' }).press('Space')
  const from = page.getByLabel('Từ ngày')
  const through = page.getByLabel('Đến hết ngày')
  const requestsBeforeCustom = seen.length
  await expect(through).toHaveValue('2026-11-19')
  await from.fill('2026-02-25')
  await through.fill('2026-02-24')
  await page.getByRole('button', { name: 'Áp dụng' }).press('Enter')
  await expect(page.getByRole('alert')).toContainText('Ngày bắt đầu')
  expect(seen).toHaveLength(requestsBeforeCustom)
  await expect(summary(page).locator('.admin-statistics__value').first()).toHaveText('20')

  await through.fill('2026-02-28')
  await page.getByRole('button', { name: 'Áp dụng' }).press('Enter')
  await expect.poll(() => seen.at(-1)).toEqual({ from: '2026-02-25', to: '2026-03-01' })
  await expect(through).toHaveValue('2026-02-28')
  await expect(summary(page).locator('.admin-statistics__value').first()).toHaveText('20')

  const requestsBeforeLimit = seen.length
  await from.fill('2026-03-01')
  await through.fill('2026-04-01')
  await page.getByRole('button', { name: 'Áp dụng' }).press('Enter')
  await expect(page.getByRole('alert')).toHaveText('Chọn khoảng thời gian tối đa 31 ngày.')
  expect(seen).toHaveLength(requestsBeforeLimit)
  await through.fill('2026-03-31')
  await page.getByRole('button', { name: 'Áp dụng' }).press('Enter')
  await expect.poll(() => seen.at(-1)).toEqual({ from: '2026-03-01', to: '2026-04-01' })
})

test('từ chối khách và User trước khi tải thống kê', async ({ page, browser }) => {
  await fixture(page, { auth: false })
  const requests: string[] = []
  const denyRequest = async (route: Route) => { requests.push(route.request().url()); await route.abort() }
  await page.route(statisticsApi, denyRequest)
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/login$/)

  const userPage = await browser.newPage({ baseURL: new URL(page.url()).origin })
  await fixture(userPage, { denied: 403 })
  await userPage.route(statisticsApi, denyRequest)
  await userPage.goto('/admin')
  await expect(userPage.getByRole('heading', { name: 'Bạn chưa có quyền quản trị' })).toBeVisible()
  await expect(userPage).toHaveURL(/\/admin$/)
  await expect(userPage).toHaveTitle('Quản trị · Văn Lang')
  await expect(summary(userPage)).toHaveCount(0)
  expect(requests).toEqual([])
  await userPage.close()
})

test('URL frontend cũ hiển thị trang không tìm thấy cho cả khách và Admin', async ({ browser, baseURL }) => {
  for (const auth of [false, true]) {
    const page = await browser.newPage({ baseURL })
    try {
      const mock = await fixture(page, { auth })
      await page.goto('/admin/statistics')
      await expect(page.getByRole('heading', { name: 'Không tìm thấy trang' })).toBeVisible()
      await expect(page).toHaveURL(/\/admin\/statistics$/)
      await expect(page).toHaveTitle('Quản trị · Văn Lang')
      await expect(page.getByRole('link', { name: 'Về trang Tổng quan' })).toHaveAttribute('href', '/admin')
      await expect(page.getByRole('heading', { name: 'Tổng quan', exact: true })).toHaveCount(0)
      await expect(page.getByRole('heading', { name: 'Quản lý tài liệu', exact: true })).toHaveCount(0)
      expect(mock.requests.some(request => new URL(request.url()).pathname === '/admin/statistics')).toBe(false)
    } finally {
      await page.close()
    }
  }
})

test('đăng nhập giữ đích Quản lý tài liệu và mở trực tiếp sau khi làm mới', async ({ page, baseURL }) => {
  await fixture(page, { auth: false })
  const destination = '/admin/sources?view=documents#admin-main'
  await page.goto(destination)
  await expect(page).toHaveURL(/\/login$/)
  await signIn(page)
  await expect(page).toHaveURL(baseURL + destination)
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu' })).toBeVisible()
  await expect(page).toHaveURL(baseURL + destination)
  await expect(page).toHaveTitle('Quản trị · Văn Lang')
})

for (const [status, heading] of [[401, 'Phiên đăng nhập đã hết hạn'], [403, 'Bạn chưa có quyền quản trị']] as const) {
  test('xử lý ' + status + ' từ API thống kê sau khi đã qua cổng quản trị', async ({ page }) => {
    await fixture(page)
    await page.route(statisticsApi, route => route.fulfill({ status, json: { detail: 'server detail' } }))
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    await expect(page.getByText('server detail')).toHaveCount(0)
    await expect(summary(page)).toHaveCount(0)
  })
}

test('lỗi API có thể thử lại trong cùng khoảng ngày', async ({ page }) => {
  await fixture(page)
  const seen: ReturnType<typeof dates>[] = []
  let available = false
  await page.route(statisticsApi, async route => {
    seen.push(dates(route))
    if (!available) await route.fulfill({ status: 503, json: { detail: 'private backend detail' } })
    else await reply(route)
  })
  await page.goto('/admin')
  await expect(page.getByRole('alert')).toHaveText('Chưa tải được số liệu thống kê. Hãy thử lại.')
  await expect(page.getByText('private backend detail')).toHaveCount(0)
  const failedRequests = seen.length
  available = true
  await page.getByRole('button', { name: 'Thử lại' }).press('Enter')
  await expect(summary(page).locator('.admin-statistics__value').first()).toHaveText('20')
  expect(seen.length).toBeGreaterThan(failedRequests)
  expect(seen).toEqual(Array(seen.length).fill(seen[0]))
})

test('drawer mobile, tên dài và sử dụng bộ lọc bằng bàn phím', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await fixture(page)
  const month: AdminStatistics = { ...sample, daily_classified: Array.from({ length: 30 }, (_, index) => ({
    date: '2026-11-' + String(index + 1).padStart(2, '0'),
    count: index < 20 ? 1 : 0,
  })) }
  await page.route(statisticsApi, route => reply(route, month))
  await page.goto('/admin/sources')
  const trigger = page.getByRole('button', { name: 'Mở điều hướng' })
  await trigger.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Điều hướng quản trị' })
  await expect(drawer.getByRole('link', { name: 'Quản lý tài liệu' })).toHaveAttribute('aria-current', 'page')
  await drawer.getByRole('link', { name: 'Tổng quan' }).press('Enter')
  await expect(drawer).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page).toHaveTitle('Quản trị · Văn Lang')
  await expect(page.getByRole('banner').getByText('VLU · Quản trị', { exact: true })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Vị trí hiện tại' })).toHaveText('Quản trị / Tổng quan')
  await expect(page.getByRole('button', { name: 'Cách đọc số liệu' })).toBeVisible()
  const presets = page.getByRole('group', { name: 'Khoảng thời gian' })
  await presets.getByRole('button', { name: '7 ngày' }).focus()
  await page.keyboard.press('Tab')
  await expect(presets.getByRole('button', { name: '30 ngày' })).toBeFocused()
  await page.keyboard.press('Space')
  await expect(presets.getByRole('button', { name: '30 ngày' })).toHaveAttribute('aria-pressed', 'true')
  const outcomes = page.getByRole('region', { name: 'Kết quả xử lý' })
  const documents = page.getByRole('region', { name: 'Tài liệu được trích dẫn nhiều' })
  const metrics = summary(page).locator('.admin-statistics__metric')
  await expect(metrics.first()).toHaveCSS('border-bottom-width', '1px')
  const [total, answered, partial] = await metrics.evaluateAll(items => items.map(item => {
    const { x, y, width } = item.getBoundingClientRect()
    return { x, y, width }
  }))
  expect(total.y).toBeLessThan(answered.y)
  expect(answered.y).toBe(partial.y)
  expect(answered.x).toBeLessThan(partial.x)
  expect(total.width).toBeCloseTo(answered.width + partial.width, 0)
  await expect(documents.getByRole('rowheader', { name: longFilename })).toBeVisible()
  await expect(documents.getByText('Đã xóa')).toBeVisible()
  const chart = page.getByRole('region', { name: 'Biểu đồ theo ngày' })
  expect(await chart.evaluate(region => region.scrollWidth > region.clientWidth)).toBe(true)
  const outcomeBox = (await outcomes.boundingBox())!
  const documentBox = (await documents.boundingBox())!
  expect(documentBox.x).toBeCloseTo(outcomeBox.x, 0)
  expect(documentBox.y).toBeGreaterThan(outcomeBox.y + outcomeBox.height)
  expect(await page.locator('#admin-main').evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('dashboard-mobile.png') })

  await trigger.press('Enter')
  await expect(drawer.getByRole('link', { name: 'Tổng quan' })).toHaveAttribute('aria-current', 'page')
  await drawer.getByRole('link', { name: 'Quản lý tài liệu' }).click()
  await expect(page.getByRole('heading', { name: 'Quản lý tài liệu' })).toBeVisible()
})
