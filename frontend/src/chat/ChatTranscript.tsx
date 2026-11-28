import { lazy, Suspense, type RefObject } from 'react'
import type { ChatTurn } from './types'
import { GoogleGrounding } from './GoogleGrounding'
import type { QuestionStage } from '../api'
import { AnswerSources } from './AnswerSources'
import { citationFileError, useCitationFile } from './useCitationFile'
import { SourceFilePreview } from '../SourceFilePreview'

const progressLabels: Record<QuestionStage | 'sending', string> = {
  sending: 'Đang gửi câu hỏi…', query: 'Đang xử lý câu hỏi…', retrieval: 'Đang tìm tài liệu…',
  generation: 'Đang soạn câu trả lời…', validation: 'Đang hoàn tất câu trả lời…',
  web_search: 'Đang xác minh thông tin trên web…',
}

const AnswerMarkdown = lazy(() => import('./AnswerMarkdown'))

type ChatTranscriptProps = {
  turns: ChatTurn[]
  isRequestPending: boolean
  accessToken: string | undefined
  containerRef: RefObject<HTMLDivElement | null>
  onRetry: (question: string, turnId: string) => void
  onScroll: () => void
  revealTurnId?: string
  onRevealEnd: () => void
}

export function ChatTranscript({ turns, isRequestPending, accessToken, containerRef, onRetry, onScroll, revealTurnId, onRevealEnd }: ChatTranscriptProps) {
  const { preview, openFile, closePreview } = useCitationFile(accessToken)

  return (
    <>
      <h1 id="conversation-heading" className="visually-hidden">Cuộc trò chuyện</h1>
      <div className="transcript" ref={containerRef} onScroll={onScroll} role="region" aria-label="Lịch sử hỏi đáp" tabIndex={0}>
        {turns.map((turn) => (
          <section className="chat-turn" key={turn.id} aria-label="Lượt hỏi đáp">
            <div className="user-message">
              <span className="message-label">Bạn</span>
              <p className="message-text">{turn.question}</p>
            </div>
            <div className="assistant-message">
              <span className="message-label assistant-identity"><span className="account-avatar assistant-avatar" aria-hidden="true">V</span>Trợ lý</span>
              {turn.status === 'pending' && (
                <p className="message-text waiting-message" role="status" aria-atomic="true">
                  <span className="waiting-dot" aria-hidden="true" />
                  <span className="waiting-label">
                    {progressLabels[turn.stage]}
                    <span className="waiting-shine" data-text={progressLabels[turn.stage]} aria-hidden="true" />
                  </span>
                </p>
              )}
              {turn.status === 'complete' && (
                <div className={revealTurnId === turn.id ? 'answer-reveal' : undefined} onAnimationEnd={onRevealEnd}>
                  {turn.response.answer && <div className="message-text answer-content">
                    <Suspense fallback={<p>{turn.response.answer}</p>}>
                      <AnswerMarkdown answer={turn.response.answer} sources={turn.response.sources} onOpenFile={openFile} />
                    </Suspense>
                  </div>}
                  <AnswerSources answer={turn.response.answer} sources={turn.response.sources} onOpenFile={openFile} />
                  {turn.response.grounding && <GoogleGrounding result={turn.response.grounding} />}
                </div>
              )}
              {turn.status === 'error' && (
                <div className="message-error" role="alert">
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
      {preview && <SourceFilePreview file={preview} describeError={citationFileError} onClose={closePreview} />}
    </>
  )
}
