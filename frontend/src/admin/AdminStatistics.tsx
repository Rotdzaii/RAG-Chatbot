import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiNetworkError } from '../api'
import { AdminDialog } from './AdminDialog'
import { adminError, getStatistics } from './adminApi'
import type { AdminStatistics, DailyClassified, StatisticsOutcome, StatisticsRange } from './adminApi'
import { useAdminResource } from './adminHooks'
import './admin-statistics.css'

const TIME_ZONE = 'Asia/Ho_Chi_Minh'
const MAX_STATISTICS_DAYS = 31
const DAY_MS = 24 * 60 * 60 * 1000
const vietnamCalendar = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
})
const countFormat = new Intl.NumberFormat('vi-VN')
const shortDayFormat = new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', day: '2-digit', month: '2-digit' })
const fullDayFormat = new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', dateStyle: 'short' })
const percentFormat = new Intl.NumberFormat('vi-VN', { style: 'percent', maximumFractionDigits: 1 })
const outcomeLabels: [StatisticsOutcome, string][] = [
  ['answered', 'Đã trả lời đủ đầu mục'],
  ['partial', 'Trả lời một phần'],
  ['insufficient_evidence', 'Thiếu bằng chứng'],
  ['clarification', 'Cần làm rõ'],
  ['unavailable', 'Không khả dụng'],
  ['error', 'Lỗi xử lý'],
]

function shiftDay(day: string, offset: number) {
  const date = new Date(day + 'T00:00:00Z')
  date.setUTCDate(date.getUTCDate() + offset)
  return date.toISOString().slice(0, 10)
}

function recentDays(days: 7 | 30): StatisticsRange {
  const parts = vietnamCalendar.formatToParts(new Date())
  const today = ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)!.value).join('-')
  return { from: shiftDay(today, 1 - days), to: shiftDay(today, 1) }
}

function formatCount(count: number | null) {
  return count == null ? '—' : countFormat.format(count)
}

function formatRatio(ratio: number | null) {
  return ratio == null ? '—' : percentFormat.format(ratio)
}

function statisticsError(error: unknown) {
  if (error instanceof ApiNetworkError) return adminError(error)
  return 'Chưa tải được số liệu thống kê. Hãy thử lại.'
}

function SummaryMetric({ label, count, variant, ratio }: {
  label: string
  count: number | null
  variant: 'total' | 'answered' | 'partial'
  ratio?: number | null
}) {
  return <div className="admin-statistics__metric" data-summary={variant}>
    <dt>{label}</dt>
    <dd className="admin-statistics__value">{formatCount(count)}</dd>
    {ratio !== undefined && <dd className="admin-statistics__rate"
      data-positive={ratio != null && ratio > 0 ? '' : undefined}>{formatRatio(ratio)}</dd>}
  </div>
}

function RatioBar({ ratio }: { ratio: number | null }) {
  return <div className="admin-statistics__track" aria-hidden="true">
    {ratio != null && ratio > 0 &&
      <div className="admin-statistics__bar" style={{ width: Math.min(ratio, 1) * 100 + '%' }} />}
  </div>
}

function DailyClassifiedChart({ days }: { days: DailyClassified[] }) {
  const peak = Math.max(1, ...days.map(day => day.count ?? 0))
  return <section className="admin-statistics__panel admin-statistics__daily" aria-labelledby="statistics-daily">
    <header>
      <h2 id="statistics-daily">Lượt đã kết thúc và được phân loại theo ngày</h2>
      <p>Theo ngày nhận câu hỏi, giờ Việt Nam. Dấu — biểu thị ngày chưa có số liệu.</p>
    </header>
    <div className="admin-statistics__chart-scroll" role="region" aria-label="Biểu đồ theo ngày" tabIndex={0}>
      <div className="admin-statistics__daily-chart" aria-hidden="true"
        style={{ gridTemplateColumns: 'repeat(' + days.length + ', minmax(31px, 1fr))' }}>
        {days.map(({ date, count }) => <div className="admin-statistics__day" key={date}>
          <span>{formatCount(count)}</span>
          <div className="admin-statistics__day-plot">
            {count != null && <div className="admin-statistics__day-bar" data-zero={count === 0 ? '' : undefined}
              style={{ height: count / peak * 100 + '%' }} />}
          </div>
          <time dateTime={date}>{shortDayFormat.format(new Date(date + 'T00:00:00Z'))}</time>
        </div>)}
      </div>
    </div>
    <details className="admin-statistics__daily-details">
      <summary>Xem bảng theo ngày</summary>
      <table className="admin-statistics__ranking" aria-label="Lượt đã kết thúc và được phân loại theo ngày">
        <thead><tr><th scope="col">Ngày nhận</th><th scope="col">Số lượt</th></tr></thead>
        <tbody>
          {days.map(({ date, count }) => <tr key={date}>
            <th scope="row"><time dateTime={date}>{fullDayFormat.format(new Date(date + 'T00:00:00Z'))}</time></th>
            <td>{count == null ? 'Chưa có số liệu' : formatCount(count)}</td>
          </tr>)}
        </tbody>
      </table>
    </details>
  </section>
}

function StatisticsReport({ report }: { report: AdminStatistics }) {
  const denominator = report.outcome_denominator
  const { answered, partial } = report.by_outcome
  return <>
    <dl className="admin-statistics__summary" aria-label="Tổng quan">
      <SummaryMetric variant="total" label="Lượt đã kết thúc và được phân loại" count={denominator} />
      <SummaryMetric variant="answered" label="Đã trả lời đủ đầu mục" count={answered.count} ratio={answered.ratio} />
      <SummaryMetric variant="partial" label="Trả lời một phần" count={partial.count} ratio={partial.ratio} />
    </dl>
    <dl className="admin-statistics__coverage" aria-label="Phạm vi ghi nhận">
      <div><dt>Chưa phân loại</dt><dd>{formatCount(report.unclassified)}</dd></div>
      <div><dt>Chưa kết thúc</dt><dd>{formatCount(report.running)}</dd></div>
      {report.cancelled > 0 && <div><dt>Đã hủy</dt><dd>{formatCount(report.cancelled)}</dd></div>}
    </dl>
    <DailyClassifiedChart days={report.daily_classified} />
    <div className="admin-statistics__details">
      <section className="admin-statistics__panel" aria-labelledby="statistics-outcomes">
        <header>
          <h2 id="statistics-outcomes">Kết quả xử lý</h2>
          <p>{denominator > 0
            ? 'Tỷ lệ tính trên ' + formatCount(denominator) + ' lượt đã kết thúc và được phân loại.'
            : report.data_started_at
              ? 'Không có lượt đã kết thúc và được phân loại trong khoảng này.'
              : 'Chưa có dữ liệu được đo.'}</p>
        </header>
        <ul className="admin-statistics__outcomes" role="list">
          {outcomeLabels.map(([key, label]) => {
            const measure = report.by_outcome[key]
            return <li key={key} data-outcome={key}>
              <span>{label}</span>
              <span className="admin-statistics__outcome-count">{formatCount(measure.count)}{measure.count != null && ' lượt'}</span>
              <span className="admin-statistics__outcome-rate">{formatRatio(measure.ratio)}</span>
              <RatioBar ratio={measure.ratio} />
            </li>
          })}
        </ul>
      </section>
      <section className="admin-statistics__panel" aria-labelledby="statistics-documents">
        <header>
          <h2 id="statistics-documents">Tài liệu được trích dẫn nhiều</h2>
          <p>{report.cited_answer_denominator > 0
            ? 'Tỷ lệ tính trên ' + formatCount(report.cited_answer_denominator) + ' câu trả lời có trích dẫn tài liệu nội bộ.'
            : 'Không có câu trả lời có trích dẫn tài liệu nội bộ trong khoảng này.'}</p>
        </header>
        {report.ranked_documents.length > 0 && <table className="admin-statistics__ranking" aria-labelledby="statistics-documents">
          <thead><tr><th scope="col">Tài liệu</th><th scope="col">Câu trả lời trích dẫn</th></tr></thead>
          <tbody>
            {report.ranked_documents.map(document => <tr key={document.document_id}>
              <th scope="row">{document.filename ?? 'Tài liệu chưa có tên'}
                {document.deleted && <span className="admin-statistics__deleted">Đã xóa</span>}
              </th>
              <td>
                <div className="admin-statistics__document-measure">
                  <span>{formatCount(document.count)}</span>
                  <span>{formatRatio(document.ratio)}</span>
                </div>
                <RatioBar ratio={document.ratio} />
              </td>
            </tr>)}
          </tbody>
        </table>}
        <div className="admin-statistics__notes">
          <p>Một đáp án trích nhiều đoạn của cùng tài liệu chỉ tính một lần.</p>
          <p>Khi xóa hội thoại, các trích dẫn của hội thoại rời bảng xếp hạng. Thống kê vận hành đã ghi được giữ lại.</p>
        </div>
      </section>
    </div>
  </>
}

export function AdminStatisticsPage({ token, onFailure }: { token: string; onFailure: (error: unknown) => void }) {
  const [reportRequest, setReportRequest] = useState(() => ({ range: recentDays(7), revision: 0 }))
  const { range, revision } = reportRequest
  const [mode, setMode] = useState<7 | 30 | 'custom'>(7)
  const [from, setFrom] = useState(range.from)
  const [through, setThrough] = useState(() => shiftDay(range.to, -1))
  const [dateError, setDateError] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const load = useCallback((signal: AbortSignal) => getStatistics(token, range, signal), [token, range])
  const { data, loading, error } = useAdminResource(String(revision), load, onFailure, statisticsError)

  function requestRange(range: StatisticsRange) {
    setReportRequest(previous => ({ range, revision: previous.revision + 1 }))
  }

  function selectRange(selection: typeof mode) {
    setMode(selection)
    setDateError('')
    if (selection === 'custom') {
      setFrom(range.from)
      setThrough(shiftDay(range.to, -1))
    } else {
      requestRange(recentDays(selection))
    }
  }

  function applyCustomRange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!from || !through || from > through) {
      setDateError('Ngày bắt đầu phải trước hoặc trùng ngày kết thúc.')
      return
    }
    if (Date.parse(through) - Date.parse(from) >= MAX_STATISTICS_DAYS * DAY_MS) {
      setDateError('Chọn khoảng thời gian tối đa 31 ngày.')
      return
    }
    setDateError('')
    requestRange({ from, to: shiftDay(through, 1) })
  }

  return <div className="admin-statistics">
    <header className="admin-section-heading admin-statistics__heading">
      <h1>Tổng quan</h1>
      <div className="admin-statistics__controls">
        <div className="admin-statistics__presets" role="group" aria-label="Khoảng thời gian">
          {([7, 30, 'custom'] as const).map(selection => <button
            key={selection} type="button" aria-pressed={mode === selection} onClick={() => selectRange(selection)}>
            {selection === 'custom' ? 'Tùy chọn' : selection + ' ngày'}
          </button>)}
        </div>
        <button className="admin-statistics__help" type="button" aria-label="Cách đọc số liệu" title="Cách đọc số liệu"
          aria-haspopup="dialog" onClick={() => setHelpOpen(true)}>?</button>
      </div>
    </header>
    {mode === 'custom' && <form className="admin-statistics__date-form" onSubmit={applyCustomRange}>
      <label>Từ ngày<input type="date" value={from} required max="9999-12-30"
        onChange={event => { setFrom(event.target.value); setDateError('') }} /></label>
      <label>Đến hết ngày<input type="date" value={through} required max="9999-12-30"
        onChange={event => { setThrough(event.target.value); setDateError('') }} /></label>
      <button className="admin-button" type="submit">Áp dụng</button>
      {dateError && <p role="alert">{dateError}</p>}
    </form>}
    {loading && <p className="admin-statistics__status" role="status">Đang tải số liệu thống kê…</p>}
    {error && <div className="admin-statistics__status">
      <p role="alert">{error}</p>
      <button className="admin-button" type="button" onClick={() => requestRange(range)}>Thử lại</button>
    </div>}
    {data && <StatisticsReport report={data} />}
    {helpOpen && <AdminDialog title="Cách đọc số liệu" busy={false} onClose={() => setHelpOpen(false)}>
      <div className="admin-dialog-body">
        <p>Thống kê quá trình xử lý, không phản ánh độ chính xác của câu trả lời.</p>
        <p>Bộ lọc nhận tối đa 31 ngày theo giờ Việt Nam và bao gồm trọn ngày kết thúc.</p>
      </div>
    </AdminDialog>}
  </div>
}
