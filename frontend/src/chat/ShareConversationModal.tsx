import { useEffect, useRef, useState } from 'react'
import type { Conversation } from './types'
import { formatSourceLocator } from './sourceLocator'

type ShareConversationModalProps = {
  isOpen: boolean
  conversation: Conversation
  onClose: () => void
}

function createPlainTextTranscript(conversation: Conversation) {
  const transcript = conversation.turns.flatMap((turn) => {
    const lines = [`Bạn:\n${turn.question}`]

    if (turn.status === 'complete') {
      lines.push(`Trợ lý:\n${turn.response.answer}`)
      if (turn.response.sources.length > 0) {
        const sources = turn.response.sources.map((source) => (
          `[${source.citation}] ${source.filename} — ${formatSourceLocator(source)}`
        ))
        lines.push(`Nguồn tham chiếu:\n${sources.join('\n')}`)
      }
    } else if (turn.status === 'pending') {
      lines.push('Trợ lý:\nĐang chờ câu trả lời.')
    } else {
      lines.push(`Trợ lý:\n${turn.message ?? 'Không thể lấy câu trả lời.'}`)
    }

    return lines
  })

  if (conversation.draft.trim()) {
    transcript.push(`Bản nháp chưa gửi:\n${conversation.draft.trim()}`)
  }

  return [`Cuộc trò chuyện: ${conversation.title}`, ...transcript].join('\n\n')
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall back to the legacy copy command when clipboard permission is unavailable.
    }
  }

  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.setAttribute('readonly', '')
  textArea.style.position = 'fixed'
  textArea.style.opacity = '0'
  document.body.appendChild(textArea)
  textArea.select()

  try {
    if (!document.execCommand('copy')) throw new Error('Copy command failed')
  } finally {
    textArea.remove()
  }
}

export function ShareConversationModal({ isOpen, conversation, onClose }: ShareConversationModalProps) {
  const dialog = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  useEffect(() => {
    if (!isOpen) return

    const previousOverflow = document.body.style.overflow
    const focusFrame = window.requestAnimationFrame(() => closeButton.current?.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      if (event.key !== 'Tab') return
      const focusableElements = dialog.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      )
      if (!focusableElements?.length) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  async function handleCopy() {
    try {
      await copyText(createPlainTextTranscript(conversation))
      setFeedback({ type: 'success', message: 'Đã sao chép nội dung cuộc trò chuyện.' })
    } catch {
      setFeedback({ type: 'error', message: 'Không thể sao chép nội dung. Vui lòng thử lại.' })
    }
  }

  return (
    <div className="chat-dialog-layer">
      <button className="chat-dialog__overlay" type="button" tabIndex={-1} aria-label="Đóng hộp thoại chia sẻ" onClick={onClose} />
      <div
        ref={dialog}
        className="chat-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-dialog-heading"
        aria-describedby="share-dialog-note"
      >
        <div className="chat-dialog__header">
          <div>
            <p className="chat-dialog__eyebrow">Cuộc trò chuyện hiện tại</p>
            <h2 id="share-dialog-heading">Chia sẻ</h2>
          </div>
          <button ref={closeButton} className="chat-dialog__close" type="button" aria-label="Đóng hộp thoại chia sẻ" onClick={onClose}>
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="m5 5 10 10M15 5 5 15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <p className="share-dialog__title" title={conversation.title}>{conversation.title}</p>
        <p className="share-dialog__note" id="share-dialog-note">
          Liên kết chia sẻ công khai sẽ khả dụng sau khi cuộc trò chuyện được lưu.
        </p>

        <button className="chat-dialog__primary-action" type="button" onClick={() => void handleCopy()}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <rect x="6.5" y="6.5" width="9" height="9" rx="1.5" />
            <path d="M13.5 6.5V5A1.5 1.5 0 0 0 12 3.5H5A1.5 1.5 0 0 0 3.5 5v7A1.5 1.5 0 0 0 5 13.5h1.5" />
          </svg>
          Sao chép nội dung
        </button>

        {feedback && (
          <p className={feedback.type === 'error' ? 'chat-dialog__feedback chat-dialog__feedback--error' : 'chat-dialog__feedback'} role={feedback.type === 'error' ? 'alert' : 'status'}>
            {feedback.message}
          </p>
        )}
      </div>
    </div>
  )
}
