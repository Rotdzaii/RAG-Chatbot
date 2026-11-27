import { lazy, Suspense, type RefObject } from 'react'
import type { ChatTurn } from './types'
import { GoogleGrounding } from './GoogleGrounding'
import type { QuestionSource, QuestionStage } from '../api'
import { CitationDownloadButton } from './CitationDownloadButton'
import { CitationLink } from './CitationLink'
import { groupCitedSources } from './citedSources'
import { formatSourceLocator } from './sourceLocator'
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

function AnswerSources({ answer, sources, onOpenFile, onDownloadFile, isFileLoading }: {
  answer: string
  sources: QuestionSource[]
  onOpenFile: (source: QuestionSource) => void
  onDownloadFile: (source: QuestionSource) => Promise<void>
  isFileLoading: boolean
}) {
  const groups = groupCitedSources(answer, sources)
  if (groups.length === 0) return null

  return (
    <div className="answer-sources">
      <h2>Nguồn tham chiếu</h2>
      <ol className="source-list">
        {groups.map((group) => {
          const sourceFile = group.sources[0]
          const versionId = sourceFile.source_file_version_id
          return (
            <li className="source-card" key={`${group.documentId}:${versionId ?? ''}`}>
              <span className="source-filename">{group.filename}</span>
              <ol className="source-passages" aria-label={`Các đoạn trích dẫn trong ${group.filename}`}>
                {group.sources.map((source) => (
                  <li key={source.citation}>
                    <CitationLink source={source} onOpenFile={onOpenFile}>
                      <span className="citation-number">[{source.citation}]</span>
                      {' '}
                      <span className="source-index">{formatSourceLocator(source)}</span>
                    </CitationLink>
                  </li>
                ))}
              </ol>
              {versionId && (
                <CitationDownloadButton filename={group.filename} disabled={isFileLoading}
                  onClick={() => void onDownloadFile(sourceFile)} />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export function ChatTranscript({ turns, isRequestPending, accessToken, containerRef, onRetry, onScroll, revealTurnId, onRevealEnd }: ChatTranscriptProps) {
  const { preview, openFile, closePreview, downloadOriginal, feedback } = useCitationFile(accessToken)

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
                  <AnswerSources answer={turn.response.answer} sources={turn.response.sources} onOpenFile={openFile}
                    onDownloadFile={downloadOriginal} isFileLoading={feedback?.kind === 'loading'} />
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
      {feedback && <p className="citation-file-feedback" role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>}
      {preview && <SourceFilePreview file={preview} describeError={citationFileError} onClose={closePreview} />}
    </>
  )
}
