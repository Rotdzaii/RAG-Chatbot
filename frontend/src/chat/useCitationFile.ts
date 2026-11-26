import { useCallback, useEffect, useRef, useState } from 'react'
import { getOriginalSourceFile, QuestionAuthenticationError, type QuestionSource } from '../api'
import { downloadFile } from '../downloadFile'

type FileFeedback = { kind: 'loading' | 'error'; message: string }

export function useCitationFile(accessToken: string | undefined) {
  const request = useRef<AbortController | null>(null)
  const [feedback, setFeedback] = useState<FileFeedback>()
  useEffect(() => () => request.current?.abort(), [])

  const openFile = useCallback(async (source: QuestionSource, download = false) => {
    if (!source.source_file_version_id || request.current) return
    if (!accessToken) {
      setFeedback({ kind: 'error', message: 'Hãy đăng nhập để mở tệp gốc.' })
      return
    }

    const target = download ? null : window.open('about:blank', '_blank')
    if (!download && !target) {
      setFeedback({ kind: 'error', message: 'Hãy cho phép mở tab mới để xem tài liệu.' })
      return
    }
    if (target) target.opener = null

    const controller = new AbortController()
    request.current = controller
    setFeedback({ kind: 'loading', message: download ? 'Đang tải tệp gốc…' : 'Đang mở tài liệu…' })

    try {
      const blob = await getOriginalSourceFile(accessToken, source.source_file_version_id, controller.signal)
      if (controller.signal.aborted) return
      if (!target) {
        downloadFile(blob, source.filename)
      } else if (!target.closed) {
        const url = URL.createObjectURL(blob)
        const page = blob.type === 'application/pdf' && source.page_start ? `#page=${source.page_start}` : ''
        window.setTimeout(() => URL.revokeObjectURL(url), 300_000)
        target.location.href = url + page
      }
      setFeedback(undefined)
    } catch (error) {
      target?.close()
      if (controller.signal.aborted) return
      setFeedback({ kind: 'error', message: error instanceof QuestionAuthenticationError
        ? 'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại để mở tệp gốc.'
        : 'Không thể mở file gốc. Tài liệu có thể không còn khả dụng cho trích dẫn này.' })
    } finally {
      if (controller.signal.aborted) target?.close()
      request.current = null
    }
  }, [accessToken])

  return { openFile, feedback }
}
