import { useLayoutEffect } from 'react'
import type { KeyboardEvent, RefObject } from 'react'
import { useVietnameseSpeechRecognition } from './useVietnameseSpeechRecognition'

type ChatComposerProps = {
  draft: string
  conversationId: string
  isPending: boolean
  inputRef: RefObject<HTMLTextAreaElement | null>
  onDraftChange: (draft: string) => void
  onSubmit: () => void
  helperText?: string | null
  describedBy?: string
  onSpeechTranscript: (conversationId: string, transcript: string) => void
}

export function ChatComposer({
  draft,
  conversationId,
  isPending,
  inputRef,
  onDraftChange,
  onSubmit,
  helperText,
  describedBy,
  onSpeechTranscript,
}: ChatComposerProps) {
  const visibleHelperText = helperText === undefined
    ? (isPending ? 'Đang chờ câu trả lời…' : 'Enter để gửi · Shift + Enter để xuống dòng')
    : helperText
  const speech = useVietnameseSpeechRecognition({
    conversationId,
    disabled: isPending,
    onFinalTranscript: onSpeechTranscript,
  })

  useLayoutEffect(() => {
    const textarea = inputRef.current
    if (!textarea) return

    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 152)}px`
  }, [draft, inputRef])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
      event.preventDefault()
      speech.cancelRecognition()
      onSubmit()
    }
  }

  return (
    <div className="composer-dock">
      <form className="composer" aria-label="Đặt câu hỏi" onSubmit={(event) => {
        event.preventDefault()
        speech.cancelRecognition()
        onSubmit()
      }}>
        <label className="visually-hidden" htmlFor="question">Câu hỏi của bạn</label>
        <textarea
          id="question"
          name="question"
          rows={1}
          ref={inputRef}
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          disabled={isPending}
          onKeyDown={handleKeyDown}
          placeholder="Ví dụ: Điều kiện xét tốt nghiệp gồm những gì?"
          aria-describedby={describedBy ?? (visibleHelperText ? 'composer-help' : undefined)}
        />
        <button
          className={speech.state === 'listening' ? 'microphone-button microphone-button--listening' : 'microphone-button'}
          type="button"
          aria-label={speech.state === 'listening' ? 'Dừng nhập bằng giọng nói' : speech.state === 'stopping' ? 'Đang dừng nhập bằng giọng nói' : 'Bắt đầu nhập bằng giọng nói'}
          aria-pressed={speech.state !== 'idle'}
          aria-describedby={speech.message ? 'speech-recognition-status' : undefined}
          title={speech.state === 'listening' ? 'Dừng nghe' : 'Nhập bằng giọng nói'}
          disabled={isPending || speech.state === 'stopping'}
          onClick={speech.toggleRecognition}
        >
          {speech.state === 'listening' ? (
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
              <rect x="6" y="6" width="8" height="8" rx="1.5" />
            </svg>
          ) : (
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <rect x="7" y="2.8" width="6" height="10" rx="3" />
              <path d="M4.8 9.5a5.2 5.2 0 0 0 10.4 0M10 14.7v2.5M7.4 17.2h5.2" strokeLinecap="round" />
            </svg>
          )}
        </button>
        <button type="submit" className="send-button" aria-label="Gửi câu hỏi" disabled={isPending || !draft.trim()}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M10 15V5m-4 4 4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
      {speech.message && (
        <p
          className={speech.hasError ? 'speech-recognition-status speech-recognition-status--error' : 'speech-recognition-status'}
          id="speech-recognition-status"
          role={speech.hasError ? 'alert' : 'status'}
        >
          {speech.message}
        </p>
      )}
      {visibleHelperText && <p className="composer-help" id="composer-help">{visibleHelperText}</p>}
    </div>
  )
}
