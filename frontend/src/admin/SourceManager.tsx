import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { uploadDocument } from '../api'
import type { SourceMetadataInput } from '../api'
import { AdminDialog } from './AdminDialog'
import { SourceActions } from './SourceActions'
import type { SourceAction } from './SourceActions'
import { deleteSource, getSource, importSourceURL, patchSourceStatus, listSources, patchSourceMetadata, refreshSourceURL, replaceSourceFile, sourceFile } from './adminApi'
import type { KnowledgeSource } from './adminApi'
import { useAdminMutation, useAdminResource } from './adminHooks'

type Filters = SourceMetadataInput & { type: string; active: string }
const emptyFilters: Filters = { type: '', active: '' }
type Dialog = { action: SourceAction; source: KnowledgeSource } | { action: 'add' | 'filters' }

export function SourceManager({ token, onFailure }: { token: string; onFailure: (error: unknown) => void }) {
  const [offset, setOffset] = useState(0)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [draft, setDraft] = useState<Filters>(emptyFilters)
  const [filterExtraOpen, setFilterExtraOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const [dialog, setDialog] = useState<Dialog>()
  const [mode, setMode] = useState('file')
  const [url, setURL] = useState('')
  const [file, setFile] = useState<File>()
  const [validation, setValidation] = useState('')
  const [category, setCategory] = useState('')
  const [audience, setAudience] = useState('')
  const [editedMetadata, setEditedMetadata] = useState<SourceMetadataInput>({})
  const load = useCallback((signal: AbortSignal) => listSources(token, offset, filters.type, signal, 20, { category: filters.category || undefined, audience: filters.audience || undefined }, filters.active), [token, offset, filters])
  const page = useAdminResource(`${token}:${offset}:${revision}:${JSON.stringify(filters)}`, load, onFailure)
  const mutation = useAdminMutation(onFailure)
  const reload = () => setRevision(value => value + 1)
  const close = () => { setDialog(undefined); setValidation('') }
  const open = (next: Dialog) => { mutation.clear(); setValidation(''); setFile(undefined); setEditedMetadata({}); setDialog(next) }
  const source = dialog && 'source' in dialog ? dialog.source : undefined
  const chips = ([
    ['type', 'Loại nguồn', filters.type === 'file' ? 'PDF / TXT' : filters.type === 'url' ? 'URL' : ''],
    ['active', 'Trạng thái', filters.active === 'true' ? 'Đang bật' : filters.active === 'false' ? 'Đã tắt' : ''],
    ['category', 'Phân loại', filters.category ?? ''], ['audience', 'Đối tượng', filters.audience ?? ''],
  ] as const).filter(([, , value]) => value)

  function validatedFile() {
    try { if (!file) throw new Error('Hãy chọn tài liệu trước khi tiếp tục.'); return sourceFile(file) }
    catch (error) { setValidation(error instanceof Error ? error.message : 'Tài liệu chưa hợp lệ.') }
  }

  function addSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (mutation.pending) return
    setValidation('')
    const metadata = { ...(category.trim() ? { category } : {}), ...(audience.trim() ? { audience } : {}) }
    const done = () => { close(); setCategory(''); setAudience(''); setURL(''); reload() }
    if (mode === 'file') {
      const selected = validatedFile(); if (!selected) return
      void mutation.run(async () => { await uploadDocument(selected, token, metadata); return `Đã thêm tài liệu “${selected.name}”.` }, done)
    } else {
      let parsed: URL
      try { parsed = new URL(url.trim()) } catch { setValidation('Nhập địa chỉ URL hợp lệ.'); return }
      if (parsed.protocol !== 'https:' || !['vlu.edu.vn', 'www.vlu.edu.vn'].includes(parsed.hostname) || parsed.username || parsed.password || parsed.port || parsed.hash) {
        setValidation('Dùng URL HTTPS thuộc vlu.edu.vn hoặc www.vlu.edu.vn, không có thông tin đăng nhập, cổng riêng hoặc phần #.'); return
      }
      void mutation.run(async () => { await importSourceURL(token, url.trim(), metadata); return 'Đã thêm nguồn URL.' }, done)
    }
  }

  function action(action: SourceAction, item: KnowledgeSource) {
    if (action === 'original') {
      if (item.source_type === 'url' && item.source_url) window.open(item.source_url, '_blank', 'noopener,noreferrer')
    } else open({ action, source: item })
  }

  const title = dialog?.action === 'add' ? 'Thêm nguồn' : dialog?.action === 'filters' ? 'Lọc nguồn' : dialog?.action === 'details' ? 'Chi tiết nguồn' : dialog?.action === 'metadata' ? 'Sửa thông tin nguồn' : dialog?.action === 'delete' ? 'Xóa nguồn tài liệu?' : dialog?.action === 'status' ? (source?.is_active ? 'Tắt nguồn?' : 'Bật lại nguồn?') : dialog?.action === 'refresh' ? 'Cập nhật từ URL' : 'Thay file nguồn'

  return <>
    <div className="admin-section-heading admin-sources-heading"><div><h1>Quản lý nguồn</h1><p>Quản lý tài liệu dùng để trả lời và dẫn nguồn.</p></div><button className="admin-button admin-button--primary" disabled={mutation.pending} onClick={() => open({ action: 'add' })}>+ Thêm nguồn</button></div>
    {mutation.message && <p className="admin-feedback admin-feedback--success" role="status">{mutation.message}</p>}
    {mutation.error && !dialog && <p className="admin-feedback admin-feedback--error" role="alert">{mutation.error}</p>}
    <section className="admin-register" aria-label="Danh sách nguồn">
      <div className="admin-register__toolbar"><h2>Kho tài liệu {page.data && <span>{page.data.total} nguồn</span>}</h2><button className="admin-button" disabled={mutation.pending} onClick={() => { setDraft({ ...filters }); setFilterExtraOpen(Boolean(filters.category || filters.audience)); open({ action: 'filters' }) }}>Bộ lọc{chips.length > 0 && <span className="admin-filter-count">{chips.length}</span>}</button><button className="admin-more-button" aria-label="Tải lại danh sách" title="Tải lại danh sách" disabled={mutation.pending || page.loading} onClick={reload}>↻</button></div>
      {chips.length > 0 && <div className="admin-filter-chips" aria-label="Điều kiện đang áp dụng">{chips.map(([key, label, value]) => <button className="admin-filter-chip" key={key} disabled={mutation.pending} aria-label={`Bỏ lọc ${label}`} onClick={() => { setFilters(current => ({ ...current, [key]: '' })); setOffset(0) }}>{label}: {value} <span aria-hidden="true">×</span></button>)}</div>}
      <div className="admin-source-columns" aria-hidden="true"><span>Tên tài liệu</span><span>Trạng thái</span><span>Cập nhật</span><span /></div>
      {page.loading ? <p className="admin-empty" role="status">Đang tải nguồn…</p> : page.error ? <div className="admin-empty"><p role="alert">{page.error}</p><button className="admin-button" onClick={reload}>Thử tải lại</button></div>
        : !page.data?.items.length ? <div className="admin-empty"><h3>Chưa có nguồn trong danh sách này</h3><p>{chips.length ? 'Thử thay đổi hoặc xóa bộ lọc.' : 'Chọn + Thêm nguồn để tải PDF, TXT hoặc nhập URL VLU.'}</p></div>
          : <ul className="admin-source-list">{page.data.items.map(item => <li className="admin-source-row" key={item.id}>
            <div className="admin-source-name-cell"><span className={`admin-file-badge admin-file-badge--${item.source_type}`} aria-hidden="true">{item.source_type === 'url' ? 'URL' : item.mime_type === 'application/pdf' ? 'PDF' : 'TXT'}</span><div className="admin-source-info"><h3><button className="admin-source-name" title={item.filename} onClick={() => action('details', item)}>{item.filename}</button></h3><p className="admin-source-meta">{item.source_type === 'url' ? 'URL' : item.mime_type === 'application/pdf' ? 'PDF' : 'TXT'} · {item.chunk_count} đoạn tài liệu</p></div></div>
            <div className="admin-source-status-cell"><span className={`admin-source-status admin-source-status--${item.is_active ? 'active' : 'inactive'}`}>{item.is_active ? 'Đang bật' : 'Đã tắt'}</span></div><time className="admin-source-date" dateTime={item.updated_at}>{formatDate(item.updated_at, true)}</time><SourceActions source={item} busy={mutation.pending} onAction={action} />
          </li>)}</ul>}
      <div className="admin-pagination"><span>{page.data ? `Hiển thị ${page.data.items.length} / ${page.data.total} nguồn` : ''}</span><div><button className="admin-button" disabled={!offset || page.loading || mutation.pending} onClick={() => setOffset(value => Math.max(0, value - 20))}>Trang trước</button><span>Trang {offset / 20 + 1}</span><button className="admin-button" disabled={page.loading || mutation.pending || !page.data || offset + 20 >= page.data.total} onClick={() => setOffset(value => value + 20)}>Trang sau</button></div></div>
    </section>
    {mutation.pending && !dialog && <p className="admin-working" role="status">Đang xử lý nguồn. Vui lòng chờ kết quả trước khi gửi lại.</p>}
    {dialog && <AdminDialog title={title} busy={mutation.pending} onClose={close}>
      {dialog.action === 'filters' ? <form onSubmit={event => { event.preventDefault(); setFilters({ ...draft, category: draft.category?.trim() || undefined, audience: draft.audience?.trim() || undefined }); setOffset(0); close() }}>
        <div className="admin-dialog-body"><label className="admin-field">Loại nguồn<select aria-label="Loại nguồn" data-dialog-initial-focus value={draft.type} onChange={event => setDraft(value => ({ ...value, type: event.target.value }))}><option value="">Tất cả loại nguồn</option><option value="file">PDF / TXT</option><option value="url">URL</option></select></label><label className="admin-field">Trạng thái nguồn<select aria-label="Trạng thái nguồn" value={draft.active} onChange={event => setDraft(value => ({ ...value, active: event.target.value }))}><option value="">Tất cả trạng thái</option><option value="true">Đang bật</option><option value="false">Đã tắt</option></select></label>
          <details className="admin-optional-fields" open={filterExtraOpen} onToggle={event => setFilterExtraOpen(event.currentTarget.open)}><summary>Lọc theo thông tin bổ sung</summary><div className="admin-optional-grid"><label className="admin-field">Phân loại<input value={draft.category ?? ''} onChange={event => setDraft(value => ({ ...value, category: event.target.value }))} /></label><label className="admin-field">Đối tượng<input value={draft.audience ?? ''} onChange={event => setDraft(value => ({ ...value, audience: event.target.value }))} /></label></div><p>Nhập đúng nhãn đã lưu, kể cả chữ hoa và chữ thường. Để trống để không lọc theo nhãn đó.</p></details>
        </div><footer className="admin-dialog__actions"><button type="button" className="admin-button" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setOffset(0); close() }}>Xóa bộ lọc</button><button type="submit" className="admin-button admin-button--primary">Áp dụng</button></footer>
      </form> : dialog.action === 'add' ? <form onSubmit={addSource} aria-busy={mutation.pending}>
        <div className="admin-dialog-body"><fieldset disabled={mutation.pending}>
          <div className="admin-upload-tabs" role="tablist" aria-label="Cách thêm nguồn">{[['file', 'Tải tệp lên'], ['url', 'Nhập URL']].map(([value, label]) => <button type="button" role="tab" id={`source-tab-${value}`} key={value} aria-selected={mode === value} aria-controls="admin-upload-panel" onClick={() => { setMode(value); setValidation('') }}>{label}</button>)}</div><div id="admin-upload-panel" role="tabpanel" aria-labelledby={`source-tab-${mode}`}>
            {mode === 'file' ? <label className="admin-file-input">Chọn tài liệu<span className="admin-file-picker"><input data-dialog-initial-focus type="file" aria-label="Chọn tài liệu" accept=".pdf,.txt,application/pdf,text/plain" onChange={event => { setFile(event.target.files?.[0]); setValidation('') }} aria-describedby="admin-file-help" /><span className="admin-file-picker__button" aria-hidden="true">Chọn file</span><span aria-hidden="true">{file?.name ?? 'Chưa chọn file'}</span></span><span id="admin-file-help">PDF hoặc TXT mã hóa UTF-8, tối đa 10 MiB.</span></label> : <label className="admin-field">Địa chỉ nguồn<input type="url" required placeholder="https://www.vlu.edu.vn/…" value={url} onChange={event => setURL(event.target.value)} /><span>Trang web, PDF hoặc TXT thuộc tên miền VLU.</span></label>}
          </div><details className="admin-optional-fields"><summary>Thông tin bổ sung <span>Không bắt buộc</span></summary><div className="admin-optional-grid"><label className="admin-field">Phân loại<input value={category} onChange={event => setCategory(event.target.value)} /></label><label className="admin-field">Đối tượng<input value={audience} onChange={event => setAudience(event.target.value)} /></label></div></details>{validation && <p className="admin-field-error" role="alert">{validation}</p>}
        </fieldset><MutationFeedback pending={mutation.pending} error={mutation.error} /></div><footer className="admin-dialog__actions"><button type="button" className="admin-button" disabled={mutation.pending} onClick={close}>Hủy</button><button type="submit" className="admin-button admin-button--primary" disabled={mutation.pending}>{mutation.pending ? 'Đang xử lý…' : 'Thêm nguồn'}</button></footer>
      </form> : dialog.action === 'details' && source ? <SourceDetails sourceId={source.id} token={token} onFailure={onFailure} onClose={close} /> : source && <form onSubmit={event => {
        event.preventDefault(); if (mutation.pending) return
        const done = () => { close(); reload() }
        if (dialog.action === 'replace') {
          const selected = validatedFile(); if (!selected) return
          void mutation.run(async () => { const result = await replaceSourceFile(token, source.id, selected); return result.status === 'unchanged' ? 'Tài liệu không thay đổi.' : 'Đã thay tài liệu và cập nhật nguồn.' }, done)
        } else if (dialog.action === 'metadata') {
          if (!Object.keys(editedMetadata).length) return
          void mutation.run(async () => { await patchSourceMetadata(token, source.id, editedMetadata); return 'Đã lưu thông tin nguồn.' }, done)
        } else if (dialog.action === 'status') {
          void mutation.run(async () => { await patchSourceStatus(token, source.id, !source.is_active); return source.is_active ? 'Đã tắt nguồn.' : 'Đã bật nguồn.' }, done)
        } else if (dialog.action === 'refresh') {
          void mutation.run(async () => { const result = await refreshSourceURL(token, source.id); return result.status === 'unchanged' ? 'Nội dung URL không thay đổi.' : 'Đã cập nhật nội dung URL và nguồn trả lời.' }, done)
        } else if (dialog.action === 'delete') {
          void mutation.run(async () => { await deleteSource(token, source.id); return 'Đã xóa nguồn tài liệu.' }, () => { close(); if (page.data?.items.length === 1 && offset) setOffset(value => value - 20); else reload() })
        }
      }}><div className="admin-dialog-body"><p className="admin-dialog__filename">{source.filename}</p>
        {dialog.action === 'metadata' ? <><p>Chỉ lưu trường bạn thay đổi. Để trống một trường để xóa nhãn đó. Nội dung tài liệu được giữ nguyên.</p>{(['category', 'audience'] as const).map((key, index) => <label className="admin-field" key={key}>{key === 'category' ? 'Phân loại' : 'Đối tượng'}<input data-dialog-initial-focus={index === 0 || undefined} disabled={mutation.pending} value={editedMetadata[key] === undefined ? source[key] ?? '' : editedMetadata[key] ?? ''} onChange={event => setEditedMetadata(value => ({ ...value, [key]: event.target.value.trim() ? event.target.value : null }))} /></label>)}</>
          : dialog.action === 'replace' ? <><p>Chọn PDF hoặc TXT mới. Bản đang phục vụ được giữ lại nếu cập nhật thất bại.</p><label className="admin-file-input">Tài liệu thay thế<input data-dialog-initial-focus aria-label="Tài liệu thay thế" type="file" accept=".pdf,.txt,application/pdf,text/plain" disabled={mutation.pending} onChange={event => { setFile(event.target.files?.[0]); setValidation('') }} /></label></>
            : dialog.action === 'refresh' ? <p>Nội dung được cập nhật từ URL đã lưu. Bản hiện tại được giữ lại nếu cập nhật thất bại.</p>
              : dialog.action === 'status' ? <p>{source.is_active ? 'Nguồn sẽ không tham gia các lượt tìm kiếm mới. File gốc và dữ liệu vẫn được giữ lại; câu trả lời đã lưu không tự được sửa.' : 'Nguồn sẽ tham gia các lượt tìm kiếm mới. Hãy kiểm tra nội dung trước khi bật lại; câu trả lời đã lưu không tự được sửa.'}</p>
                : <p>Nguồn, các đoạn tài liệu và file gốc đã lưu sẽ bị xóa. Liên kết nguồn trong lịch sử có thể không mở được. Nếu chỉ muốn ngừng sử dụng tạm thời, hãy chọn Tắt nguồn.</p>}
        {!source.is_active && ['replace', 'refresh', 'metadata'].includes(dialog.action) && <p className="admin-info-strip">Nguồn đang tắt. Cập nhật giữ nguyên trạng thái tắt; hãy kiểm tra bản sửa rồi chủ động bật lại.</p>}{validation && <p className="admin-field-error" role="alert">{validation}</p>}<MutationFeedback pending={mutation.pending} error={mutation.error} />
      </div><footer className="admin-dialog__actions"><button data-dialog-initial-focus={dialog.action === 'delete' || undefined} className="admin-button" type="button" disabled={mutation.pending} onClick={close}>{dialog.action === 'delete' ? 'Giữ lại' : 'Hủy'}</button><button className="admin-button admin-button--primary" type="submit" disabled={mutation.pending || (dialog.action === 'metadata' && !Object.keys(editedMetadata).length)}>{mutation.pending ? 'Đang xử lý…' : dialog.action === 'delete' ? 'Xóa nguồn' : dialog.action === 'metadata' ? 'Lưu thông tin' : dialog.action === 'status' ? (source.is_active ? 'Tắt nguồn' : 'Bật nguồn') : dialog.action === 'refresh' ? 'Cập nhật URL' : 'Thay file'}</button></footer></form>}
    </AdminDialog>}
  </>
}

function MutationFeedback({ pending, error }: { pending: boolean; error: string }) {
  return <>{pending && <p role="status">Đang xử lý nguồn. Vui lòng chờ kết quả trước khi gửi lại.</p>}{error && <p className="admin-field-error" role="alert">{error}</p>}</>
}

function SourceDetails({ sourceId, token, onFailure, onClose }: { sourceId: string; token: string; onFailure: (error: unknown) => void; onClose: () => void }) {
  const [revision, setRevision] = useState(0)
  const load = useCallback((signal: AbortSignal) => getSource(token, sourceId, signal), [token, sourceId])
  const result = useAdminResource(`${sourceId}:${revision}`, load, onFailure)
  return <><div className="admin-dialog-body">{result.loading ? <p role="status">Đang tải thông tin nguồn…</p> : result.error ? <><p role="alert">{result.error}</p><button className="admin-button" onClick={() => setRevision(value => value + 1)}>Thử tải lại</button></> : result.data && <><p className="admin-dialog__filename">{result.data.filename}</p><dl className="admin-details-grid">{[
    ['Trạng thái', result.data.is_active ? 'Đang bật' : 'Đã tắt'], ['Loại nguồn', result.data.source_type === 'url' ? 'URL' : result.data.mime_type], ['Số đoạn', result.data.chunk_count], ['Phân loại', result.data.category ?? 'Chưa gán'], ['Đối tượng', result.data.audience ?? 'Chưa gán'], ['Tạo lúc', formatDate(result.data.created_at)], ['Cập nhật', formatDate(result.data.updated_at)], ['Kiểm tra URL', result.data.last_checked_at ? formatDate(result.data.last_checked_at) : 'Chưa có'], ['URL', result.data.source_url ?? 'Không có'], ['ID nguồn', result.data.id],
  ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p>Tắt nguồn chỉ ngừng sử dụng trong tìm kiếm mới; câu trả lời đã lưu không tự được sửa.</p></>}</div><footer className="admin-dialog__actions"><button className="admin-button" onClick={onClose}>Đóng</button></footer></>
}

function formatDate(value: string, dateOnly = false) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Chưa có ngày' : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', ...(!dateOnly ? { timeStyle: 'short' as const } : {}) }).format(date)
}
