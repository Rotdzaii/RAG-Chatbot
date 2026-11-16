import { useRef } from 'react'
import { ChatComposer } from '../chat/ChatComposer'
import { SuggestedQuestions } from '../chat/SuggestedQuestions'

export function HeroQuestionForm({ question, onQuestionChange, onLogin }: {
  question: string; onQuestionChange: (question: string) => void; onLogin: () => void
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null)

  function handleSubmit() {
    if (!question.trim()) {
      inputRef.current?.focus()
      return
    }
    onLogin()
  }

  return (
    <div className="home-question">
      <ChatComposer
        draft={question}
        conversationId="home-draft"
        isPending={false}
        inputRef={inputRef}
        onDraftChange={onQuestionChange}
        onSubmit={handleSubmit}
        onSpeechTranscript={(_id, transcript) => onQuestionChange(`${question}${question.trim() ? ' ' : ''}${transcript.trim()}`)}
        submitLabel="Đăng nhập để gửi"
        helperText={null}
        describedBy="home-question-help"
      />
      <SuggestedQuestions onSelect={(value) => {
        onQuestionChange(value)
        inputRef.current?.focus()
      }} />
      <p className="empty-chat__helper" id="home-question-help">
        Đăng nhập để gửi câu hỏi. Câu nháp sẽ được giữ lại để bạn kiểm tra trước khi gửi.
      </p>
    </div>
  )
}
