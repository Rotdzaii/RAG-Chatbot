import { useEffect, useRef, useState } from 'react'
import { askQuestion } from './api'
import type { QuestionResponse } from './api'
import vluLogo from './assets/vlu-logo.svg'
import { AccountControl } from './auth/AccountControl'
import './App.css'

type Turn = {
  id: number
  question: string
} & (
  | { status: 'pending' }
  | { status: 'complete'; response: QuestionResponse }
  | { status: 'error' }
)

function App() {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [pending, setPending] = useState(false)
  const requestInFlight = useRef(false)
  const nextId = useRef(0)
  const transcript = useRef<HTMLDivElement>(null)
  const composerInput = useRef<HTMLTextAreaElement>(null)
  const hasMessages = turns.length > 0

  useEffect(() => {
    const container = transcript.current
    if (container) container.scrollTop = container.scrollHeight
  }, [turns])

  useEffect(() => {
    if (hasMessages && !pending) composerInput.current?.focus()
  }, [hasMessages, pending])

  async function sendQuestion(text: string, retryId?: number) {
    const trimmedQuestion = text.trim()
    if (!trimmedQuestion || requestInFlight.current) return

    requestInFlight.current = true
    setPending(true)
    const id = retryId ?? nextId.current++
    const turn: Turn = { id, question: trimmedQuestion, status: 'pending' }
    setTurns((previous) => retryId === undefined
      ? [...previous, turn]
      : previous.map((item) => item.id === id ? turn : item))
    if (retryId === undefined) setQuestion('')

    try {
      const response = await askQuestion(trimmedQuestion)
      setTurns((previous) => previous.map((item) => item.id === id
        ? { id, question: trimmedQuestion, status: 'complete', response }
        : item))
    } catch {
      setTurns((previous) => previous.map((item) => item.id === id
        ? { id, question: trimmedQuestion, status: 'error' }
        : item))
    } finally {
      requestInFlight.current = false
      setPending(false)
    }
  }

  return (
    <div className={hasMessages ? 'app-shell app-shell--chat' : 'app-shell'} lang="vi">
      <header className="topbar">
        <a className="brand" href="#conversation" aria-label="Đại học Văn Lang, về cuộc trò chuyện">
          <img className="brand-logo" src={vluLogo} alt="Đại học Văn Lang" width={138} height={42} />
        </a>
        <AccountControl />
      </header>

      <main className={hasMessages ? 'conversation conversation--active' : 'conversation'} id="conversation" aria-labelledby={hasMessages ? 'conversation-heading' : 'welcome-heading'}>
        {!hasMessages ? <section className="welcome">
          <h1 id="welcome-heading">Bạn cần tìm thông tin gì tại Văn Lang?</h1>
          <p>Nhập câu hỏi bên dưới để bắt đầu.</p>
          <div className="context-note">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
              <path d="M3.5 4.5h5l1.5 1 1.5-1h5v11h-5L10 17l-1.5-1.5h-5zM10 5.5V17" strokeLinejoin="round" />
            </svg>
            <span>Nguồn trích dẫn sẽ nằm ngay dưới mỗi câu trả lời.</span>
          </div>
        </section> : (
          <>
            <h1 id="conversation-heading" className="visually-hidden">Cuộc trò chuyện</h1>
            <div className="transcript" ref={transcript} role="log" aria-label="Lịch sử hỏi đáp" aria-live="polite" tabIndex={0}>
              {turns.map((turn) => (
                <section className="chat-turn" key={turn.id} aria-label="Lượt hỏi đáp">
                  <div className="user-message">
                    <span className="message-label">Bạn</span>
                    <p className="message-text">{turn.question}</p>
                  </div>
                  <div className="assistant-message">
                    <span className="message-label">Trợ lý</span>
                    {turn.status === 'pending' && (
                      <p className="message-text waiting-message">
                        Đang suy nghĩ…
                      </p>
                    )}
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
                                    <span className="source-index">Đoạn {source.chunk_index}</span>
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
                        <p>Chưa thể lấy câu trả lời. Câu hỏi của bạn vẫn được giữ lại; hãy thử lại.</p>
                        <button type="button" className="retry-button" disabled={pending} onClick={() => void sendQuestion(turn.question, turn.id)}>
                          Thử lại
                        </button>
                      </div>
                    )}
                  </div>
                </section>
              ))}
            </div>
          </>
        )}

        <div className="composer-dock">
          <form className="composer" aria-label="Đặt câu hỏi" onSubmit={(event) => {
            event.preventDefault()
            void sendQuestion(question)
          }}>
            <label htmlFor="question">Câu hỏi của bạn</label>
            <textarea
              id="question"
              name="question"
              rows={2}
              ref={composerInput}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={pending}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                  event.preventDefault()
                  void sendQuestion(question)
                }
              }}
              placeholder="Ví dụ: Điều kiện xét tốt nghiệp gồm những gì?"
              aria-describedby="composer-help"
            />
            <div className="composer-toolbar">
              <button type="submit" className="send-button" aria-label="Gửi câu hỏi" disabled={pending || !question.trim()}>
                <span>Gửi</span>
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                  <path d="M10 15V5m-4 4 4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </form>
          <p className="composer-help" id="composer-help">
            Enter để gửi · Shift + Enter để xuống dòng
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
