import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { storePendingQuestion } from '../chat/pendingQuestion'

const EMPTY_QUESTION_ERROR = 'Vui lòng nhập câu hỏi trước khi tiếp tục.'
const STORAGE_ERROR = 'Không thể lưu câu hỏi trong phiên này. Vui lòng thử lại.'

export function HeroQuestionForm() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [question, setQuestion] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuestion = question.trim()

    if (!trimmedQuestion) {
      setErrorMessage(EMPTY_QUESTION_ERROR)
      inputRef.current?.focus()
      return
    }

    if (!storePendingQuestion(trimmedQuestion)) {
      setErrorMessage(STORAGE_ERROR)
      return
    }

    setErrorMessage('')

    if (user) {
      navigate('/chat')
    } else {
      navigate('/login', { state: { from: '/chat' } })
    }
  }

  return (
    <form className="hero-question" onSubmit={handleSubmit}>
      <label className="home-visually-hidden" htmlFor="hero-question-input">Câu hỏi của bạn</label>
      <input
        id="hero-question-input"
        ref={inputRef}
        name="question"
        type="text"
        value={question}
        placeholder="Ví dụ: Ngành Kỹ thuật Phần mềm học những môn nào?"
        autoComplete="off"
        aria-describedby={errorMessage ? 'hero-question-error' : 'hero-question-help'}
        onChange={(event) => {
          setQuestion(event.target.value)
          if (errorMessage) setErrorMessage('')
        }}
      />
      <button type="submit" aria-label="Gửi câu hỏi và tiếp tục">
        <span>Khám phá</span>
        <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M5 11h12m-5-5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <span className="home-visually-hidden" id="hero-question-help">
        Câu hỏi sẽ được chuyển sang trình trợ lý và không tự động gửi.
      </span>
      {errorMessage && <p className="hero-question__error" id="hero-question-error" role="alert">{errorMessage}</p>}
    </form>
  )
}
