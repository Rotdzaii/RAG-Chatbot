import { useEffect, useId, useRef, useState } from 'react'
import { PdfFilePreview } from './PdfFilePreview'
import { SourceFileIcon } from './SourceFileIcon'
import { sourceFileKind } from './downloadFile'
import './source-file-preview.css'

export type PreviewFile = {
  filename: string
  mime?: string | null
  page?: number | null
  load?: (signal: AbortSignal) => Promise<{ blob: Blob; filename: string }>
}

type PreviewResult =
  | { file: PreviewFile; error: string }
  | { file: PreviewFile; url: string; filename: string; kind: 'PDF' | 'TXT'; text?: string }

export function SourceFilePreview({ file, onClose, describeError }: {
  file: PreviewFile
  onClose: () => void
  describeError: (error: unknown) => string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const heading = useId()
  const [result, setResult] = useState<PreviewResult>()
  const current = result?.file === file ? result : undefined
  const ready = current && 'url' in current ? current : undefined
  const kind = ready?.kind ?? sourceFileKind(file.filename, file.mime)
  const page = kind === 'PDF' && file.page && Number.isInteger(file.page) && file.page > 0 ? file.page : undefined
  const pdfUrl = ready && kind === 'PDF' ? ready.url + (page ? `#page=${page}` : '') : undefined

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    dialog.showModal()
    return () => dialog.close()
  }, [])

  useEffect(() => {
    const load = file.load
    if (!load) return
    const controller = new AbortController()
    let url: string | undefined
    const read = async () => {
      if (controller.signal.aborted) return
      const { blob, filename } = await load(controller.signal)
      if (controller.signal.aborted) return
      const mime = blob.type.split(';')[0].trim().toLowerCase()
      const responseKind = sourceFileKind(filename, mime === 'application/pdf' || mime === 'text/plain' ? mime : file.mime)
      const text = responseKind === 'TXT' ? await blob.text() : undefined
      if (controller.signal.aborted) return
      // Blob navigation must use one of the two supported viewer types.
      const type = responseKind === 'PDF' ? 'application/pdf' : 'text/plain'
      url = URL.createObjectURL(blob.type === type ? blob : blob.slice(0, blob.size, type))
      setResult({ file, url, filename, kind: responseKind, text })
    }
    void Promise.resolve().then(read).catch(error => {
      if (!controller.signal.aborted) setResult({ file, error: describeError(error) })
    })
    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [file, describeError])

  function close() {
    ref.current?.close()
    onClose()
  }

  return <dialog ref={ref} className="source-preview" aria-labelledby={heading}
    onCancel={event => { event.preventDefault(); close() }}
    onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation() }}>
    <header className="source-preview__header">
      <span className="source-preview__icon"><SourceFileIcon kind={kind} /></span>
      <div>
        <p>Xem trước {kind}</p>
        <h2 id={heading}>{file.filename}</h2>
      </div>
      <button className="source-preview__close" type="button" onClick={close} aria-label="Đóng" title="Đóng">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" strokeLinecap="round" /></svg>
      </button>
    </header>
    {!file.load ? <p className="source-preview__notice" role="status">Chưa lưu tệp gốc cho trích dẫn này.</p>
      : current && 'error' in current ? <p className="source-preview__notice" role="alert">{current.error}</p>
      : !ready ? <p className="source-preview__notice" role="status">Đang tải tệp gốc…</p>
      : <>
        {pdfUrl
          ? <PdfFilePreview key={ready.url} url={ready.url} initialPage={page} />
          : <pre className="source-preview__text" tabIndex={0} aria-label="Nội dung tệp TXT">{ready.text}</pre>}
        <footer className="source-preview__actions">
          {pdfUrl && <a className="source-preview__external" href={pdfUrl} target="_blank" rel="noopener noreferrer">
            Mở trong tab mới
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M8 5h7v7M15 5l-9 9" /></svg>
          </a>}
          <a className="source-preview__download" href={ready.url} download={ready.filename}>
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 2.8v9.5m-3.5-3.6 3.5 3.6 3.5-3.6M3.5 13v3.5h13V13" /></svg>
            Tải tệp gốc
          </a>
        </footer>
      </>}
  </dialog>
}
