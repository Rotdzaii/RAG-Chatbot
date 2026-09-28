const SUGGESTED_QUESTIONS = [
  'Chương trình đào tạo ngành Kỹ thuật phần mềm gồm những gì?',
  'Điều kiện xét tốt nghiệp gồm những gì?',
  'Thông tin học phí được cập nhật như thế nào?',
] as const

type SuggestedQuestionsProps = {
  onSelect: (question: string) => void
}

export function SuggestedQuestions({ onSelect }: SuggestedQuestionsProps) {
  return (
    <section className="suggested-questions" aria-labelledby="suggested-questions-heading">
      <h2 className="visually-hidden" id="suggested-questions-heading">Câu hỏi gợi ý</h2>
      {SUGGESTED_QUESTIONS.map((question) => (
        <button key={question} type="button" onClick={() => onSelect(question)}>
          {question}
        </button>
      ))}
    </section>
  )
}
