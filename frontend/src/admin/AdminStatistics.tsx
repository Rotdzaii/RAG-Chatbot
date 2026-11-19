import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiNetworkError } from '../api'
import { adminError, getStatistics } from './adminApi'
import type { AdminStatistics, StatisticsMeasure, StatisticsOutcome, StatisticsRange } from './adminApi'
import { useAdminResource } from './adminHooks'
import './admin-statistics.css'

const TIME_ZONE = 'Asia/Ho_Chi_Minh'
const vietnamCalendar = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
})
const displayDay = new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', dateStyle: 'medium' })
const displayTime = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TIME_ZONE, dateStyle: 'medium', timeStyle: 'short',
})
const countFormat = new Intl.NumberFormat('vi-VN')
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

function formatDay(day: string) {
  return displayDay.format(new Date(day + 'T00:00:00Z'))
}

function formatCount(count: number | null) {
  return count == null ? '—' : countFormat.format(count)
}

function formatRatio(measure: StatisticsMeasure, denominator: number) {
  return !denominator || measure.ratio == null ? '—' : percentFormat.format(measure.ratio)
}

function statisticsError(error: unknown) {
  if (error instanceof ApiNetworkError) return adminError(error)
  return 'Chưa tải được số liệu thống kê. Hãy thử lại.'
}

function SummaryCard({ label, count, detail }: { label: string; count: number | null; detail?: string }) {
  return <div className="admin-statistics__summary-card">
    <dt>{label}</dt>
    <dd className="admin-statistics__value">{formatCount(count)}</dd>
    {detail && <dd className="admin-statistics__rate">{detail}</dd>}
  </div>
}

function StatisticsReport({ report }: { report: AdminStatistics }) {
  const denominator = report.outcome_denominator
  const { answered, partial } = report.by_outcome
  const lastDay = shiftDay(report.end_date, -1)
  return <>
    <p className="admin-statistics__period">
      <time dateTime={report.start_date}>{formatDay(report.start_date)}</time>
      {' – '}
      <time dateTime={lastDay}>{formatDay(lastDay)}</time>
      <span title={report.timezone}>Giờ Việt Nam</span>
    </p>
    <dl className="admin-statistics__summary" aria-label="Tổng quan">
      <SummaryCard label="Lượt đã kết thúc và được phân loại" count={denominator} />
      <SummaryCard label="Đã trả lời đủ đầu mục" count={answered.count} detail={formatRatio(answered, denominator)} />
      <SummaryCard label="Trả lời một phần" count={partial.count} detail={formatRatio(partial, denominator)} />
    </dl>
    <dl className="admin-statistics__coverage" aria-label="Phạm vi ghi nhận">
      <div><dt>Chưa phân loại</dt><dd>{formatCount(report.unclassified)}</dd></div>
      <div><dt>Chưa kết thúc</dt><dd>{formatCount(report.running)}</dd></div>
      {report.cancelled > 0 && <div><dt>Đã hủy</dt><dd>{formatCount(report.cancelled)}</dd></div>}
      <div>
        <dt>Bắt đầu thu thập</dt>
        <dd>{report.data_started_at
          ? <time dateTime={report.data_started_at}>{displayTime.format(new Date(report.data_started_at))}</time>
          : 'Chưa có mốc ghi nhận'}</dd>
      </div>
    </dl>
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
            return <li key={key}>
              <span>{label}</span>
              <span className="admin-statistics__outcome-count">{formatCount(measure.count)}{measure.count != null && ' lượt'}</span>
              <span className="admin-statistics__outcome-rate">{formatRatio(measure, denominator)}</span>
              <div className="admin-statistics__track" aria-hidden="true">
                <div className="admin-statistics__bar" style={{ width: (denominator ? (measure.ratio ?? 0) * 100 : 0) + '%' }} />
              </div>
            </li>
          })}
        </ul>
      </section>
      <section className="admin-statistics__panel" aria-labelledby="statistics-documents">
        <header>
          <h2 id="statistics-documents">Tài liệu được trích dẫn nhiều</h2>
          <p>{report.cited_answer_denominator > 0
            ? formatCount(report.cited_answer_denominator) + ' câu trả lời có trích dẫn tài liệu hợp lệ.'
            : 'Không có câu trả lời có trích dẫn tài liệu hợp lệ trong khoảng này.'}</p>
        </header>
        {report.ranked_documents.length > 0 && <table className="admin-statistics__ranking" aria-labelledby="statistics-documents">
          <thead><tr><th scope="col">Tài liệu</th><th scope="col">Số câu trả lời trích dẫn</th></tr></thead>
          <tbody>
            {report.ranked_documents.map(document => <tr key={document.document_id}>
              <th scope="row">{document.filename ?? 'Tài liệu chưa có tên'}
                {document.deleted && <span className="admin-statistics__deleted">Đã xóa</span>}
              </th>
              <td>{formatCount(document.count)}</td>
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
    setDateError('')
    requestRange({ from, to: shiftDay(through, 1) })
  }

  return <div className="admin-statistics">
    <header className="admin-section-heading admin-statistics__heading">
      <div>
        <h1>Tổng quan</h1>
        <p>Thống kê quá trình xử lý, không phản ánh độ chính xác của câu trả lời.</p>
      </div>
      <div className="admin-statistics__presets" role="group" aria-label="Khoảng thời gian">
        {([7, 30, 'custom'] as const).map(selection => <button
          key={selection} type="button" aria-pressed={mode === selection} onClick={() => selectRange(selection)}>
          {selection === 'custom' ? 'Tùy chọn' : selection + ' ngày'}
        </button>)}
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
  </div>
}
