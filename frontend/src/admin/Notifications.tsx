import { useCallback, useState } from 'react'
import { listNotifications, markNotificationRead } from './adminApi'
import { useAdminMutation, useAdminResource } from './adminHooks'

export function Notifications({ token, onFailure }: { token: string; onFailure: (error: unknown) => void }) {
  const [offset, setOffset] = useState(0)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [revision, setRevision] = useState(0)
  const load = useCallback((signal: AbortSignal) => listNotifications(token, offset, unreadOnly, signal), [token, offset, unreadOnly])
  const page = useAdminResource(`${token}:${offset}:${unreadOnly}:${revision}`, load, onFailure)
  const mutation = useAdminMutation(onFailure)
  const reload = () => setRevision(value => value + 1)
  return <>
    <div className="admin-section-heading"><div><h1>Thông báo</h1><p>Theo dõi thay đổi của những URL đã đăng ký.</p></div>
      <button className="admin-button" disabled={page.loading || mutation.pending} onClick={reload}>Tải lại thông báo</button></div>
    <p className="admin-info-strip">Phát hiện thay đổi không tự cập nhật kho trả lời. Bạn có thể cập nhật URL tại Quản lý nguồn sau khi xem xét.</p>
    {mutation.message && <p className="admin-feedback admin-feedback--success" role="status">{mutation.message}</p>}
    {mutation.error && <p className="admin-feedback admin-feedback--error" role="alert">{mutation.error}</p>}
    <section className="admin-register" aria-label="Thông báo thay đổi URL">
      <div className="admin-register__toolbar"><h2>Thay đổi nguồn URL</h2>
        <label className="admin-checkbox"><input type="checkbox" checked={unreadOnly} disabled={mutation.pending} onChange={event => { setUnreadOnly(event.target.checked); setOffset(0) }} />Chỉ chưa đọc</label></div>
      {page.loading ? <p className="admin-empty" role="status">Đang tải thông báo…</p>
        : page.error ? <div className="admin-empty"><p role="alert">{page.error}</p><button className="admin-button" onClick={reload}>Thử tải lại</button></div>
          : !page.data?.length ? <div className="admin-empty"><h3>{unreadOnly ? 'Không có thông báo chưa đọc' : 'Chưa có thông báo ở trang này'}</h3><p>Khi URL đã đăng ký có thay đổi, thông báo sẽ xuất hiện tại đây.</p></div>
            : <ul className="admin-notification-list">{page.data.map(item => <li key={item.id} className={`admin-notification ${item.read_at ? '' : 'admin-notification--unread'}`}>
              <span className="admin-notification-dot" aria-hidden="true" />
              <div className="admin-source-info"><div className="admin-notification-heading"><h3>Nội dung URL đã thay đổi</h3><span className="admin-read-badge">{item.read_at ? 'Đã đọc' : 'Chưa đọc'}</span></div>
                <p className="admin-source-url">{item.source_url}</p>
                <p className="admin-source-meta">Phát hiện {new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(item.detected_at))}</p>
                <p className="admin-notification-note">Nguồn trả lời vẫn giữ nội dung đã nhập trước đó.</p>
              </div>
              {!item.read_at && <button className="admin-button" disabled={mutation.pending} onClick={() => void mutation.run(async () => {
                await markNotificationRead(token, item.id); return 'Đã đánh dấu thông báo là đã đọc.'
              }, () => { if (unreadOnly && page.data?.length === 1 && offset > 0) setOffset(value => value - 20); else reload() })}>Đánh dấu đã đọc</button>}
            </li>)}</ul>}
      <div className="admin-pagination"><button className="admin-button" disabled={offset === 0 || page.loading || mutation.pending} onClick={() => setOffset(value => Math.max(0, value - 20))}>Trang trước</button>
        <span>Trang {offset / 20 + 1}</span><button className="admin-button" disabled={page.loading || mutation.pending || !page.data || page.data.length < 20} onClick={() => setOffset(value => value + 20)}>Trang sau</button></div>
    </section>
    {mutation.pending && <p className="admin-working" role="status">Đang đánh dấu đã đọc…</p>}
  </>
}
