import { lazy, Suspense, type RefObject } from 'react'
import type { QuestionSource } from '../api'
import type { ChatTurn } from './types'
import { formatSourceLocator } from './sourceLocator'
import { groupCitedSources } from './citedSources'

const AnswerMarkdown = lazy(() => import('./AnswerMarkdown'))

type ChatTranscriptProps = {
  turns: ChatTurn[]
  isRequestPending: boolean
  containerRef: RefObject<HTMLDivElement | null>
  onRetry: (question: string, turnId: string) => void
}

function AnswerSources({ answer, sources }: { answer: string; sources: QuestionSource[] }) {
  const groups = groupCitedSources(answer, sources)
  if (groups.length === 0) return null

  return (
    <div className="answer-sources">
      <h2>Nguồn tham chiếu</h2>
      <ol className="source-list">
        {groups.map((group) => (
          <li className="source-card" key={group.documentId}>
            <span className="source-filename">{group.filename}</span>
            <ol className="source-passages" aria-label={`Các đoạn trích dẫn trong ${group.filename}`}>
              {group.sources.map((source) => (
                <li key={source.chunk_id}>
                  <span className="citation-number" aria-label={`Trích dẫn ${source.citation}`}>[{source.citation}]</span>
                  <span className="source-index">{formatSourceLocator(source)}</span>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
    </div>
  )
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
                  <div className="message-text answer-content">
                    <Suspense fallback={<p>{turn.response.answer}</p>}>
                      <AnswerMarkdown answer={turn.response.answer} />
                    </Suspense>
                  </div>
                  <AnswerSources answer={turn.response.answer} sources={turn.response.sources} />
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
