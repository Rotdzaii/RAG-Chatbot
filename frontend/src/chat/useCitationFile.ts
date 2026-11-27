import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getOriginalSourceFile, QuestionAuthenticationError, type QuestionSource } from '../api'
import { downloadFile } from '../downloadFile'
import type { PreviewFile } from '../SourceFilePreview'

type FileFeedback = { kind: 'loading' | 'error'; message: string }

export function citationFileError(error: unknown) {
  return error instanceof QuestionAuthenticationError
    ? 'Hãy đăng nhập lại để mở tệp gốc.'
    : 'Không thể mở tệp gốc. Tài liệu có thể không còn khả dụng cho trích dẫn này.'
}

export function useCitationFile(accessToken: string | undefined) {
  const [source, openFile] = useState<QuestionSource>()
  const [feedback, setFeedback] = useState<FileFeedback>()
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [accessToken])

  const preview = useMemo<PreviewFile | undefined>(() => {
    if (!source) return
    const { filename, mime_type: mime, page_start: page, source_file_version_id: version } = source
    return { filename, mime, page, load: version ? async signal => ({
      filename, blob: await getOriginalSourceFile(accessToken, version, signal),
    }) : undefined }
  }, [source, accessToken])

  const downloadOriginal = useCallback(async (source: QuestionSource) => {
    if (!source.source_file_version_id || request.current) return
    const controller = new AbortController()
    request.current = controller
    setFeedback({ kind: 'loading', message: 'Đang tải tệp gốc…' })
    try {
      const blob = await getOriginalSourceFile(accessToken, source.source_file_version_id, controller.signal)
      if (controller.signal.aborted) return
      downloadFile(blob, source.filename)
      setFeedback(undefined)
    } catch (error) {
      if (!controller.signal.aborted) setFeedback({ kind: 'error', message: citationFileError(error) })
    } finally {
      request.current = null
      if (controller.signal.aborted) setFeedback(undefined)
    }
  }, [accessToken])

  return { preview, openFile, closePreview: () => openFile(undefined), downloadOriginal, feedback }
}
