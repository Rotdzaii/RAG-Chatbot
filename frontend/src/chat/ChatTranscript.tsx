import type { RefObject } from 'react'
import type { ChatTurn } from './types'
import { formatSourceLocator } from './sourceLocator'

type ChatTranscriptProps = {
  turns: ChatTurn[]
  isRequestPending: boolean
  containerRef: RefObject<HTMLDivElement | null>
  onRetry: (question: string, turnId: string) => void
}

export function ChatTranscript({ turns, isRequestPending, containerRef, onRetry }: ChatTranscriptProps) {
  return (
    <>
      <h1 id="conversation-heading" className="visually-hidden">Cuộc trò chuyện</h1>
      <div className="transcript" ref={containerRef} role="log" aria-label="Lịch sử hỏi đáp" aria-live="polite" tabIndex={0}>
        {turns.map((turn) => (
          <section className="chat-turn" key={turn.id} aria-label="Lượt hỏi đáp">
            <div className="user-message">
              <span className="message-label">Bạn</span>
              <p className="message-text">{turn.question}</p>
            </div>
            <div className="assistant-message">
              <span className="message-label">Trợ lý</span>
              {turn.status === 'pending' && <p className="message-text waiting-message">Đang suy nghĩ…</p>}
              {turn.status === 'complete' && (
                <>
                  <p className="message-text">{turn.response.answer}</p>
                  {turn.response.sources.length > 0 && (
                    <div className="answer-sources">
                      <h2>Nguồn tham chiếu</h2>
                      <ol className="source-list">
                        {turn.response.sources.map((source, index) => (
                          <li className="source-card" key={`${source.chunk_id}-${index}`}>
                            <span className="citation-number" aria-label={`Trích dẫn ${source.citation}`}>[{source.citation}]</span>
                            <div>
                              <span className="source-filename">{source.filename}</span>
                              <span className="source-index">{formatSourceLocator(source)}</span>
                            </div>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                </>
              )}
              {turn.status === 'error' && (
                <div className="message-error">
                  <p>{turn.message ?? 'Chưa thể lấy câu trả lời. Câu hỏi của bạn vẫn được giữ lại; hãy thử lại.'}</p>
                  <button type="button" className="retry-button" disabled={isRequestPending} onClick={() => onRetry(turn.question, turn.id)}>
                    Thử lại
                  </button>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </>
  )
}
