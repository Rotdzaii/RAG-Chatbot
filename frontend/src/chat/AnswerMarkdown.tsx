import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function AnswerMarkdown({ answer }: { answer: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
      {answer.replace(/<br\s*\/?\s*>/gi, '  \n')}
    </ReactMarkdown>
  )
}
