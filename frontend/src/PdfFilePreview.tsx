import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'

export function PdfFilePreview({ url, initialPage }: { url: string; initialPage?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const scrollArea = useRef<HTMLDivElement>(null)
  const [document, setDocument] = useState<PDFDocumentProxy>()
  const [documentFailed, setDocumentFailed] = useState(false)
  const [requestedPage, setRequestedPage] = useState(initialPage ?? 1)
  const [pageResult, setPageResult] = useState<{ page: number; loaded: boolean }>()
  const page = document ? Math.min(requestedPage, document.numPages) : requestedPage
  const loaded = pageResult?.page === page && pageResult.loaded
  const failed = documentFailed || (pageResult?.page === page && !pageResult.loaded)

  useEffect(() => {
    let active = true
    let task: PDFDocumentLoadingTask | undefined
    const open = async () => {
      const [{ getDocument, GlobalWorkerOptions }, { PdfAssetLoader, workerUrl }] = await Promise.all([
        import('pdfjs-dist/legacy/build/pdf.mjs'),
        import('./pdfPreviewAssets'),
      ])
      if (!active) return
      GlobalWorkerOptions.workerSrc = workerUrl
      task = getDocument({ url, isEvalSupported: false, BinaryDataFactory: PdfAssetLoader, useWorkerFetch: false })
      const pdf = await task.promise
      if (active) setDocument(pdf)
    }
    void open().catch(() => { if (active) setDocumentFailed(true) })
    return () => {
      active = false
      void task?.destroy().catch(() => {})
    }
  }, [url])

  useEffect(() => {
    const target = canvas.current
    if (!document || !target) return
    let active = true
    let task: RenderTask | undefined
    const render = async () => {
      const pdfPage = await document.getPage(page)
      if (!active) return
      const { width, height } = pdfPage.getViewport({ scale: 1 })
      const viewport = pdfPage.getViewport({ scale: Math.min(2, 1800 / Math.max(width, height)) })
      target.width = Math.ceil(viewport.width)
      target.height = Math.ceil(viewport.height)
      task = pdfPage.render({ canvas: target, viewport })
      await task.promise
      if (active) {
        if (scrollArea.current) scrollArea.current.scrollTop = 0
        setPageResult({ page, loaded: true })
      }
    }
    void render().catch(() => { if (active) setPageResult({ page, loaded: false }) })
    return () => {
      active = false
      task?.cancel()
    }
  }, [document, page])

  function goToPage(nextPage: number) {
    setPageResult(undefined)
    setRequestedPage(nextPage)
  }

  return (
    <div className="source-preview__pdf">
      {document && <nav className="source-preview__pdf-nav" aria-label="Điều hướng trang PDF">
        <button type="button" disabled={page <= 1} onClick={() => goToPage(page - 1)}>Trang trước</button>
        <span aria-live="polite">Trang {page} / {document.numPages}</span>
        <button type="button" disabled={page >= document.numPages} onClick={() => goToPage(page + 1)}>Trang sau</button>
      </nav>}
      <div className="source-preview__pdf-page" ref={scrollArea} tabIndex={0} role="region" aria-label="Nội dung tệp PDF">
        {failed && <p className="source-preview__notice" role="alert">Không thể hiển thị PDF trong cửa sổ này. Chọn “Mở trong tab mới” để xem tệp.</p>}
        {!loaded && !failed && <p className="source-preview__notice" role="status">Đang hiển thị PDF…</p>}
        <canvas ref={canvas} hidden={!loaded} role="img" aria-label={`Trang ${page}`} />
      </div>
    </div>
  )
}
