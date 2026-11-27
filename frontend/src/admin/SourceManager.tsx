import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { uploadDocument } from '../api'
import type { SourceMetadataInput } from '../api'
import { downloadFile } from '../downloadFile'
import { AdminDialog } from './AdminDialog'
import { SourceActions } from './SourceActions'
import type { SourceAction } from './SourceActions'
import { adminError, deleteSource, getSource, getSourceDownload, importSourceURL, patchSourceStatus, listSources, patchSourceMetadata, refreshSourceURL, replaceSourceFile, sourceDownloadError, sourceFile } from './adminApi'
import type { KnowledgeSource } from './adminApi'
import { useAdminMutation, useAdminResource } from './adminHooks'
import { SourceSearch } from './SourceSearch'

type Filters = SourceMetadataInput & { type: string }
const emptyFilters: Filters = { type: '' }
const pageSize = 20
const sourceTabs = [{ active: true, label: 'Đang sử dụng' }, { active: false, label: 'Tạm ngưng' }]
type Dialog = { action: Exclude<SourceAction, 'original' | 'download' | 'status'>; source: KnowledgeSource }
  | { action: 'add' | 'filters' }
  | { action: 'status'; sources: KnowledgeSource[] }
type StatusFailure = { source: KnowledgeSource; reason: unknown }

export function SourceManager({ token, onFailure }: { token: string; onFailure: (error: unknown) => void }) {
  const [active, setActive] = useState(true)
  const selectedTab = useRef<HTMLButtonElement>(null)
  const restoreTabFocus = useRef(false)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [statusFailures, setStatusFailures] = useState<StatusFailure[]>([])
  const [filename, setFilename] = useState('')
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
  const load = useCallback(async (signal: AbortSignal) => {
    const result = await listSources(token, offset, filters.type, signal, pageSize, {
      category: filters.category || undefined, audience: filters.audience || undefined,
    }, String(active), filename)
    if (!signal.aborted && offset && !result.items.length) {
      const lastOffset = Math.max(0, Math.ceil(result.total / pageSize) - 1) * pageSize
      if (lastOffset < offset) setOffset(lastOffset)
    }
    return result
  }, [token, offset, filters, active, filename])
  const page = useAdminResource(JSON.stringify([token, offset, revision, filters, active, filename]), load, onFailure)
  const mutation = useAdminMutation(onFailure)
  const reload = () => setRevision(value => value + 1)
  const close = () => { setDialog(undefined); setValidation('') }
  const open = (next: Dialog) => { mutation.clear(); setValidation(''); setFile(undefined); setEditedMetadata({}); setDialog(next) }
  const source = dialog && 'source' in dialog ? dialog.source : undefined
  const items = page.data?.items ?? []
  const selectedItems = items.filter(item => selected.has(item.id))
  const allSelected = items.length > 0 && selectedItems.length === items.length
  const statusLabel = active ? 'Tạm ngưng' : 'Bật lại'
  const chips = ([
    ['type', 'Loại tài liệu', filters.type === 'file' ? 'PDF / TXT' : filters.type === 'url' ? 'URL' : ''],
    ['category', 'Phân loại', filters.category ?? ''], ['audience', 'Đối tượng', filters.audience ?? ''],
  ] as const).filter(([, , value]) => value)

  useEffect(() => {
    if (dialog || !restoreTabFocus.current) return
    restoreTabFocus.current = false
    selectedTab.current?.focus({ preventScroll: true })
  }, [dialog])

  function changePage(nextOffset: number) {
    setSelected(new Set())
    setOffset(nextOffset)
  }

  function changeTab(nextActive: boolean) {
    if (nextActive === active || mutation.pending) return
    setActive(nextActive)
    changePage(0)
    setStatusFailures([])
    mutation.clear()
  }

  function updateStatus(sources: KnowledgeSource[]) {
    const failures: StatusFailure[] = []
    setStatusFailures([])
    void mutation.run(async () => {
      const results = await Promise.allSettled(sources.map(item => patchSourceStatus(token, item.id, !active)))
      results.forEach((result, index) => {
        if (result.status === 'rejected') failures.push({ source: sources[index], reason: result.reason })
      })
      const count = sources.length - failures.length
      return count ? `Đã ${statusLabel.toLocaleLowerCase('vi')} ${count} tài liệu.` : ''
    }, () => {
      failures.forEach(({ reason }) => onFailure(reason))
      setStatusFailures(failures)
      const updated = new Set(sources.map(item => item.id))
      setSelected(current => new Set([
        ...Array.from(current).filter(id => !updated.has(id)),
        ...failures.map(({ source }) => source.id),
      ]))
      restoreTabFocus.current = true
      close()
      reload()
    })
  }

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
      void mutation.run(async () => { await importSourceURL(token, url.trim(), metadata); return 'Đã thêm tài liệu từ liên kết.' }, done)
    }
  }

  function action(action: SourceAction, item: KnowledgeSource) {
    if (action === 'original') {
      if (item.source_type === 'url' && item.source_url) window.open(item.source_url, '_blank', 'noopener,noreferrer')
    } else if (action === 'download') {
      void mutation.run(async () => {
        const { blob, filename } = await getSourceDownload(token, item)
        downloadFile(blob, filename)
        return `Đã gửi tệp “${filename}” đến trình duyệt để tải xuống.`
      }, undefined, sourceDownloadError)
    } else if (action === 'status') open({ action, sources: [item] })
    else open({ action, source: item })
  }

  const title = dialog?.action === 'add' ? 'Thêm tài liệu' : dialog?.action === 'filters' ? 'Lọc tài liệu' : dialog?.action === 'details' ? 'Chi tiết tài liệu' : dialog?.action === 'metadata' ? 'Sửa thông tin tài liệu' : dialog?.action === 'delete' ? 'Xóa tài liệu?' : dialog?.action === 'status' ? `${statusLabel} tài liệu?` : dialog?.action === 'refresh' ? 'Cập nhật từ liên kết' : 'Thay file tài liệu'

  return <>
    <div className="admin-section-heading admin-sources-heading"><div><h1>Quản lý tài liệu</h1><p>Quản lý tài liệu dùng để trả lời và dẫn nguồn.</p></div><button className="admin-button admin-button--primary" disabled={mutation.pending} onClick={() => open({ action: 'add' })}>+ Thêm tài liệu</button></div>
    {mutation.message && <p className="admin-feedback admin-feedback--success" role="status">{mutation.message}</p>}
    {mutation.error && !dialog && <p className="admin-feedback admin-feedback--error" role="alert">{mutation.error}</p>}
    {statusFailures.length > 0 && <div className="admin-feedback admin-feedback--error admin-status-failures">
      <div role="alert">
        <strong>Không thể {statusLabel.toLocaleLowerCase('vi')} {statusFailures.length} tài liệu sau:</strong>
        <ul>{statusFailures.map(({ source, reason }) => <li key={source.id}><strong>{source.filename}</strong> · {adminError(reason)}</li>)}</ul>
      </div>
      <button className="admin-button" disabled={mutation.pending} onClick={() => open({ action: 'status', sources: statusFailures.map(({ source }) => source) })}>Thử lại các mục lỗi</button>
    </div>}
    <div className="admin-register__tabs" role="tablist" aria-label="Trạng thái tài liệu">
      {sourceTabs.map(tab => <button
        key={tab.label} ref={active === tab.active ? selectedTab : undefined} type="button" role="tab"
        id={`admin-source-tab-${tab.active}`} aria-controls="admin-source-panel" aria-selected={active === tab.active}
        aria-disabled={mutation.pending && active !== tab.active} tabIndex={active === tab.active ? 0 : -1}
        onClick={() => changeTab(tab.active)} onKeyDown={event => {
          if (mutation.pending || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
          event.preventDefault()
          const nextActive = event.key === 'Home' ? true : event.key === 'End' ? false : !active
          event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`#admin-source-tab-${nextActive}`)?.focus()
          changeTab(nextActive)
        }}
      >{tab.label}</button>)}
    </div>
    <section className="admin-register" id="admin-source-panel" role="tabpanel" aria-labelledby={`admin-source-tab-${active}`}>
      <div className="admin-register__toolbar"><h2>Kho tài liệu {page.data && <span>{page.data.total} tài liệu</span>}</h2><SourceSearch value={filename} disabled={mutation.pending} onChange={value => { setFilename(value); changePage(0) }} /><button className="admin-button" disabled={mutation.pending} onClick={() => { setDraft({ ...filters }); setFilterExtraOpen(Boolean(filters.category || filters.audience)); open({ action: 'filters' }) }}>Bộ lọc{chips.length > 0 && <span className="admin-filter-count">{chips.length}</span>}</button><button className="admin-more-button" aria-label="Tải lại danh sách" title="Tải lại danh sách" disabled={mutation.pending || page.loading} onClick={reload}>↻</button></div>
      {chips.length > 0 && <div className="admin-filter-chips" aria-label="Điều kiện đang áp dụng">{chips.map(([key, label, value]) => <button className="admin-filter-chip" key={key} disabled={mutation.pending} aria-label={`Bỏ lọc ${label}`} onClick={() => { setFilters(current => ({ ...current, [key]: '' })); changePage(0) }}>{label}: {value} <span aria-hidden="true">×</span></button>)}</div>}
      <div className="admin-source-columns">
        <input id="admin-source-select-all" className="admin-source-checkbox" type="checkbox" aria-label="Chọn tất cả tài liệu trên trang này"
          checked={allSelected} disabled={mutation.pending || !items.length}
          ref={input => { if (input) input.indeterminate = selectedItems.length > 0 && !allSelected }}
          onChange={event => setSelected(new Set(event.target.checked ? items.map(item => item.id) : []))} />
        <label className="admin-source-select-label" htmlFor="admin-source-select-all">
          {selectedItems.length ? <span role="status">Đã chọn {selectedItems.length}</span> : <><span className="admin-source-column-name">Tên tài liệu</span><span className="admin-source-select-page">Chọn cả trang</span></>}
        </label>
        <span className="admin-source-date">Cập nhật</span>
        <button className="admin-button admin-source-status-button" disabled={!selectedItems.length || mutation.pending}
          onClick={() => open({ action: 'status', sources: selectedItems })}>{statusLabel}</button>
      </div>
      {page.loading ? <p className="admin-empty" role="status">Đang tải tài liệu…</p> : page.error ? <div className="admin-empty"><p role="alert">{page.error}</p><button className="admin-button" onClick={reload}>Thử tải lại</button></div>
        : !items.length ? <div className="admin-empty"><h3>Chưa có tài liệu trong danh sách này</h3>{(filename.trim() || chips.length > 0 || active) && <p>{filename.trim() ? 'Thử từ khóa khác, xóa từ khóa hoặc thay đổi bộ lọc.' : chips.length ? 'Thử thay đổi hoặc xóa bộ lọc.' : 'Chọn + Thêm tài liệu để tải PDF, TXT hoặc nhập URL VLU.'}</p>}</div>
          : <ul className="admin-source-list">{items.map(item => <li className="admin-source-row" key={item.id}>
            <input className="admin-source-checkbox" type="checkbox" aria-label={`Chọn ${item.filename}`} checked={selected.has(item.id)} disabled={mutation.pending}
              onChange={event => {
                const checked = event.target.checked
                setSelected(current => {
                  const next = new Set(current)
                  if (checked) next.add(item.id)
                  else next.delete(item.id)
                  return next
                })
              }} />
            <div className="admin-source-name-cell">
              <span className={`admin-file-badge admin-file-badge--${item.source_type}`} aria-hidden="true">{item.source_type === 'url' ? 'URL' : item.mime_type === 'application/pdf' ? 'PDF' : 'TXT'}</span>
              <div className="admin-source-info">
                <h3><button className="admin-source-name" title={item.filename} disabled={mutation.pending} onClick={() => action('details', item)}>{item.filename}</button></h3>
                <p className="admin-source-meta">{item.source_type === 'url' ? 'URL' : item.mime_type === 'application/pdf' ? 'PDF' : 'TXT'} · {item.chunk_count} đoạn tài liệu</p>
                {item.source_type === 'file' && (
                  <button type="button" className="admin-source-download" disabled={mutation.pending}
                    aria-label={`Tải tệp gốc · ${item.filename}`} onClick={() => action('download', item)}>
                    Tải tệp gốc
                  </button>
                )}
              </div>
            </div>
            <time className="admin-source-date" dateTime={item.updated_at}>{formatDate(item.updated_at, true)}</time>
            <div className="admin-source-row-actions">
              {!active && <button type="button" className="admin-button admin-source-status-button" disabled={mutation.pending}
                aria-label={`Bật lại ${item.filename}`} onClick={() => action('status', item)}>Bật lại</button>}
              <SourceActions source={item} busy={mutation.pending} onAction={action} />
            </div>
          </li>)}</ul>}
      <div className="admin-pagination"><span>{page.data ? `Hiển thị ${items.length} / ${page.data.total} tài liệu` : ''}</span><div><button className="admin-button" disabled={!offset || page.loading || mutation.pending} onClick={() => changePage(Math.max(0, offset - pageSize))}>Trang trước</button><span>Trang {offset / pageSize + 1}</span><button className="admin-button" disabled={page.loading || mutation.pending || !page.data || offset + pageSize >= page.data.total} onClick={() => changePage(offset + pageSize)}>Trang sau</button></div></div>
    </section>
    {mutation.pending && !dialog && <p className="admin-working" role="status">Đang xử lý tài liệu. Vui lòng chờ kết quả trước khi gửi lại.</p>}
    {dialog && <AdminDialog title={title} busy={mutation.pending} onClose={close}>
      {dialog.action === 'filters' ? <form onSubmit={event => { event.preventDefault(); setFilters({ ...draft, category: draft.category?.trim() || undefined, audience: draft.audience?.trim() || undefined }); changePage(0); close() }}>
        <div className="admin-dialog-body"><label className="admin-field">Loại tài liệu<select aria-label="Loại tài liệu" data-dialog-initial-focus value={draft.type} onChange={event => setDraft(value => ({ ...value, type: event.target.value }))}><option value="">Tất cả loại tài liệu</option><option value="file">PDF / TXT</option><option value="url">URL</option></select></label>
          <details className="admin-optional-fields" open={filterExtraOpen} onToggle={event => setFilterExtraOpen(event.currentTarget.open)}><summary>Lọc theo thông tin bổ sung</summary><div className="admin-optional-grid"><label className="admin-field">Phân loại<input value={draft.category ?? ''} onChange={event => setDraft(value => ({ ...value, category: event.target.value }))} /></label><label className="admin-field">Đối tượng<input value={draft.audience ?? ''} onChange={event => setDraft(value => ({ ...value, audience: event.target.value }))} /></label></div><p>Nhập đúng nhãn đã lưu, kể cả chữ hoa và chữ thường. Để trống để không lọc theo nhãn đó.</p></details>
        </div><footer className="admin-dialog__actions"><button type="button" className="admin-button" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); changePage(0); close() }}>Xóa bộ lọc</button><button type="submit" className="admin-button admin-button--primary">Áp dụng</button></footer>
      </form> : dialog.action === 'add' ? <form onSubmit={addSource} aria-busy={mutation.pending}>
        <div className="admin-dialog-body"><fieldset disabled={mutation.pending}>
          <div className="admin-upload-tabs" role="tablist" aria-label="Cách thêm tài liệu">{[['file', 'Tải tệp lên'], ['url', 'Nhập URL']].map(([value, label]) => <button type="button" role="tab" id={`source-tab-${value}`} key={value} aria-selected={mode === value} aria-controls="admin-upload-panel" onClick={() => { setMode(value); setValidation('') }}>{label}</button>)}</div><div id="admin-upload-panel" role="tabpanel" aria-labelledby={`source-tab-${mode}`}>
            {mode === 'file' ? <label className="admin-file-input">Chọn tài liệu<span className="admin-file-picker"><input data-dialog-initial-focus type="file" aria-label="Chọn tài liệu" accept=".pdf,.txt,application/pdf,text/plain" onChange={event => { setFile(event.target.files?.[0]); setValidation('') }} aria-describedby="admin-file-help admin-file-naming-help" /><span className="admin-file-picker__button" aria-hidden="true">Chọn file</span><span aria-hidden="true">{file?.name ?? 'Chưa chọn file'}</span></span><span id="admin-file-help">PDF hoặc TXT mã hóa UTF-8, tối đa 10 MiB.</span><span id="admin-file-naming-help">Gợi ý đặt tên: ky-thuat-phan-mem_k32_chuong-trinh-dao-tao.pdf (không bắt buộc).</span></label> : <label className="admin-field">Địa chỉ liên kết<input type="url" required placeholder="https://www.vlu.edu.vn/…" value={url} onChange={event => setURL(event.target.value)} /><span>Trang web, PDF hoặc TXT thuộc tên miền VLU.</span></label>}
          </div><details className="admin-optional-fields"><summary>Thông tin bổ sung <span>Không bắt buộc</span></summary><div className="admin-optional-grid"><label className="admin-field">Phân loại<input value={category} onChange={event => setCategory(event.target.value)} /></label><label className="admin-field">Đối tượng<input value={audience} onChange={event => setAudience(event.target.value)} /></label></div></details>{validation && <p className="admin-field-error" role="alert">{validation}</p>}
        </fieldset><MutationFeedback pending={mutation.pending} error={mutation.error} /></div><footer className="admin-dialog__actions"><button type="button" className="admin-button" disabled={mutation.pending} onClick={close}>Hủy</button><button type="submit" className="admin-button admin-button--primary" disabled={mutation.pending}>{mutation.pending ? 'Đang xử lý…' : 'Thêm tài liệu'}</button></footer>
      </form> : dialog.action === 'status' ? <form aria-busy={mutation.pending} onSubmit={event => {
        event.preventDefault()
        if (!mutation.pending) updateStatus(dialog.sources)
      }}>
        <div className="admin-dialog-body">
          {dialog.sources.length === 1 ? <p className="admin-dialog__filename">{dialog.sources[0].filename}</p> :
            <p>{dialog.sources.length} tài liệu đã chọn</p>}
          <p>{active ? 'Các lượt tìm kiếm mới sẽ bỏ qua tài liệu đã chọn. Tệp gốc và dữ liệu vẫn được lưu.' : 'Tài liệu sẽ được sử dụng lại trong các lượt tìm kiếm mới.'} Câu trả lời đã lưu được giữ nguyên.</p>
          <MutationFeedback pending={mutation.pending} error={mutation.error} />
        </div>
        <footer className="admin-dialog__actions">
          <button className="admin-button" type="button" disabled={mutation.pending} onClick={close}>Hủy</button>
          <button className="admin-button admin-button--primary" type="submit" disabled={mutation.pending}>{mutation.pending ? 'Đang xử lý…' : statusLabel}</button>
        </footer>
      </form> : dialog.action === 'details' && source ? <SourceDetails sourceId={source.id} token={token} onFailure={onFailure} onClose={close} /> : source && <form onSubmit={event => {
        event.preventDefault(); if (mutation.pending) return
        const done = () => { close(); reload() }
        if (dialog.action === 'replace') {
          const selected = validatedFile(); if (!selected) return
          void mutation.run(async () => { const result = await replaceSourceFile(token, source.id, selected); return result.status === 'unchanged' ? 'Tài liệu không thay đổi.' : 'Đã thay tài liệu.' }, done)
        } else if (dialog.action === 'metadata') {
          if (!Object.keys(editedMetadata).length) return
          void mutation.run(async () => { await patchSourceMetadata(token, source.id, editedMetadata); return 'Đã lưu thông tin tài liệu.' }, done)
        } else if (dialog.action === 'refresh') {
          void mutation.run(async () => { const result = await refreshSourceURL(token, source.id); return result.status === 'unchanged' ? 'Nội dung từ liên kết không thay đổi.' : 'Đã cập nhật tài liệu từ liên kết.' }, done)
        } else if (dialog.action === 'delete') {
          void mutation.run(async () => { await deleteSource(token, source.id); return 'Đã xóa tài liệu.' }, done)
        }
      }}><div className="admin-dialog-body"><p className="admin-dialog__filename">{source.filename}</p>
        {dialog.action === 'metadata' ? <><p>Chỉ lưu trường bạn thay đổi. Để trống một trường để xóa nhãn đó. Nội dung tài liệu được giữ nguyên.</p>{(['category', 'audience'] as const).map((key, index) => <label className="admin-field" key={key}>{key === 'category' ? 'Phân loại' : 'Đối tượng'}<input data-dialog-initial-focus={index === 0 || undefined} disabled={mutation.pending} value={editedMetadata[key] === undefined ? source[key] ?? '' : editedMetadata[key] ?? ''} onChange={event => setEditedMetadata(value => ({ ...value, [key]: event.target.value.trim() ? event.target.value : null }))} /></label>)}</>
          : dialog.action === 'replace' ? <><p>Chọn PDF hoặc TXT mới. Bản đang phục vụ được giữ lại nếu cập nhật thất bại.</p><label className="admin-file-input">Tài liệu thay thế<input data-dialog-initial-focus aria-label="Tài liệu thay thế" type="file" accept=".pdf,.txt,application/pdf,text/plain" disabled={mutation.pending} onChange={event => { setFile(event.target.files?.[0]); setValidation('') }} /></label></>
            : dialog.action === 'refresh' ? <p>Nội dung được cập nhật từ liên kết đã lưu. Bản hiện tại được giữ lại nếu cập nhật thất bại.</p>
              : <p>Tài liệu, các đoạn nội dung và file gốc đã lưu sẽ bị xóa. Liên kết tài liệu trong lịch sử có thể không mở được.</p>}
        {!source.is_active && ['replace', 'refresh', 'metadata'].includes(dialog.action) && <p className="admin-info-strip">Tài liệu đang tạm ngưng sử dụng. Cập nhật giữ nguyên trạng thái tạm ngưng; hãy kiểm tra bản sửa rồi chủ động cho phép sử dụng.</p>}{validation && <p className="admin-field-error" role="alert">{validation}</p>}<MutationFeedback pending={mutation.pending} error={mutation.error} />
      </div><footer className="admin-dialog__actions"><button data-dialog-initial-focus={dialog.action === 'delete' || undefined} className="admin-button" type="button" disabled={mutation.pending} onClick={close}>{dialog.action === 'delete' ? 'Giữ lại' : 'Hủy'}</button><button className="admin-button admin-button--primary" type="submit" disabled={mutation.pending || (dialog.action === 'metadata' && !Object.keys(editedMetadata).length)}>{mutation.pending ? 'Đang xử lý…' : dialog.action === 'delete' ? 'Xóa tài liệu' : dialog.action === 'metadata' ? 'Lưu thông tin' : dialog.action === 'refresh' ? 'Cập nhật từ liên kết' : 'Thay file'}</button></footer></form>}
    </AdminDialog>}
  </>
}

function MutationFeedback({ pending, error }: { pending: boolean; error: string }) {
  return <>{pending && <p role="status">Đang xử lý tài liệu. Vui lòng chờ kết quả trước khi gửi lại.</p>}{error && <p className="admin-field-error" role="alert">{error}</p>}</>
}

function SourceDetails({ sourceId, token, onFailure, onClose }: { sourceId: string; token: string; onFailure: (error: unknown) => void; onClose: () => void }) {
  const [revision, setRevision] = useState(0)
  const load = useCallback((signal: AbortSignal) => getSource(token, sourceId, signal), [token, sourceId])
  const result = useAdminResource(`${sourceId}:${revision}`, load, onFailure)
  return <><div className="admin-dialog-body">{result.loading ? <p role="status">Đang tải thông tin tài liệu…</p> : result.error ? <><p role="alert">{result.error}</p><button className="admin-button" onClick={() => setRevision(value => value + 1)}>Thử tải lại</button></> : result.data && <><p className="admin-dialog__filename">{result.data.filename}</p><dl className="admin-details-grid">{[
    ['Trạng thái sử dụng', result.data.is_active ? 'Đang sử dụng' : 'Tạm ngưng'], ['Loại tài liệu', result.data.source_type === 'url' ? 'URL' : result.data.mime_type], ['Số đoạn', result.data.chunk_count], ['Phân loại', result.data.category ?? 'Chưa gán'], ['Đối tượng', result.data.audience ?? 'Chưa gán'], ['Tạo lúc', formatDate(result.data.created_at)], ['Cập nhật', formatDate(result.data.updated_at)], ['Kiểm tra URL', result.data.last_checked_at ? formatDate(result.data.last_checked_at) : 'Chưa có'], ['URL', result.data.source_url ?? 'Không có'], ['ID tài liệu', result.data.id],
  ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p>Tạm ngưng sử dụng chỉ áp dụng cho các lượt tìm kiếm mới; câu trả lời đã lưu không tự được sửa.</p></>}</div><footer className="admin-dialog__actions"><button className="admin-button" onClick={onClose}>Đóng</button></footer></>
}

function formatDate(value: string, dateOnly = false) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Chưa có ngày' : new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', ...(!dateOnly ? { timeStyle: 'short' as const } : {}) }).format(date)
}
